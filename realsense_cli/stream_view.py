import io
import re
import threading
import time
from types import TracebackType

from loguru import logger
from rich.box import SIMPLE_HEAD
from rich.console import Console, Group
from rich.measure import Measurement
from rich.panel import Panel

from realsense_cli.preview import PreviewMode, preview_image, render
from realsense_cli.types import Frame, FrameSet, Profile


class StreamView(Panel):
    def __init__(self, streams: list[str] | None = None, metadata: bool = True):
        logger.info("StreamView created")
        self._metadata = metadata
        self._dynamic = not streams
        self._panels: dict[str, Panel] = {}
        self._title_set: dict[str, bool] = {}
        self._prev_frame: dict[str, Frame | None] = {}
        self._regroup(streams)

        super().__init__(Group(*self._panels.values()), box=SIMPLE_HEAD, title_align="center")

    def update(self, frames: FrameSet | None):
        if not frames:
            frames = {}
        logger.debug("updating view for frameset {}", frames.keys())
        for stream, frame in frames.items():
            if stream not in self._panels:
                if not self._dynamic:
                    continue
                else:
                    logger.debug("new stream in dynamic mode, regrouping")
                    self._regroup([stream])
            profile = frame.profile
            if not self._title_set[stream]:
                self._panels[stream].title = self._gen_panel_title(profile)
                self._title_set[stream] = True

            metrics = {"index": frame.index, "fps": self._calc_fps(frame)}
            panel_str: list[str] = [f"Frame #{metrics['index']:<8} FPS: {metrics['fps']:<4.2f}"]
            if self._metadata and frame.metadata:
                longest = max(len(m) for m in frame.metadata.keys())
                for md, val in frame.metadata.items():
                    name = md.replace("_", " ").title()
                    panel_str.append(f"{name.ljust(longest + 1)}={str(val).rjust(15)}")
            self._panels[stream].renderable = "\n".join(panel_str)
            self._panels[stream].width = max(
                self._panels[stream].width or 0, len(panel_str[-1]) + 4
            )

    def _regroup(self, streams: list[str] | None):
        logger.info("Regroup for streams {}", streams)
        if not streams:
            streams = []
        for stream in streams:
            panel = Panel("...", title=stream, width=35)
            self._panels[stream] = panel
            self._title_set[stream] = False
            self._prev_frame[stream] = None

        self.renderable = Group(*self._panels.values())

    @property
    def panels(self):
        return self._panels

    def _gen_panel_title(self, profile: Profile) -> str:
        res = profile.resolution
        return (
            f"{profile.stream} ({profile.index}) {res.width}x{res.height} "
            f"{profile.fps}fps {profile.format}"
        )

    def _calc_fps(self, frame: Frame) -> float:
        stream = frame.profile.stream
        prev_frame = self._prev_frame[stream]
        if not prev_frame:
            self._prev_frame[stream] = frame
            return 0
        num = frame.index - prev_frame.index
        delta = frame.timestamp - prev_frame.timestamp
        logger.debug("calc fps {} - num = {}, delta = {}", frame.profile.stream, num, delta)
        self._prev_frame[stream] = frame
        if not delta:
            return 0

        return 1000 * (num / delta)


# The narrowest image worth drawing beside the panels: a narrower one goes above them
MIN_SIDE_IMAGE = 24

# Seconds between checks for a terminal resize while no update arrives
RESIZE_CHECK = 0.25

_SGR = re.compile(r"\x1b\[[0-9;]*m")


class PreviewLive:
    """
    The live view of `rs stream play --preview`: VIEW's panels beside an image of STREAM's
    newest frame in MODE, redrawn from a thread as each update arrives, at most REFRESH times a
    second, and on a terminal resize. The image is written as escape
    codes, not through Rich, which costs several times more per frame. On a terminal it draws
    in the alternate screen, so a slow terminal drops frames rather than scrolling; on anything
    else it prints the last view once on exit, as Live does
    """

    def __init__(
        self,
        view: StreamView,
        stream: str,
        mode: PreviewMode,
        console: Console,
        refresh: float = 30,
    ):
        self._view = view
        self._stream = stream
        self._mode = mode
        self._console = console
        self._interval = 1 / refresh
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._changed = True
        self._size: tuple[int, int] | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._panels = Console(
            file=io.StringIO(),
            # the name Rich detected, which its own parameter takes
            color_system=console.color_system,  # ty: ignore[invalid-argument-type]
            force_terminal=console.is_terminal,
            no_color=console.no_color,
            legacy_windows=False,
        )

    def update(self, frames: FrameSet | None) -> None:
        with self._lock:
            self._view.update(frames)
            if frames and self._stream in frames:
                self._frame = frames[self._stream]
            self._changed = True
        self._wake.set()

    def __enter__(self) -> "PreviewLive":
        if self._console.is_terminal:
            self._write("\x1b[?1049h\x1b[?25l")
            self._wake.set()  # the first draw: no need to wait for an update
            self._thread = threading.Thread(target=self._refresh, name="preview", daemon=True)
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._thread is None:
            width, height = self._console.size
            self._write("\n".join(line.rstrip() for line in self.lines(width, height)) + "\n")
            return
        self._stop.set()
        self._wake.set()
        self._thread.join()
        self._write("\x1b[0m\x1b[?25h\x1b[?1049l")

    def lines(self, width: int, height: int) -> list[str]:
        """
        The view in WIDTH x HEIGHT cells: the image left of the panels, or above them when the
        two don't fit side by side
        """
        with self._lock:
            frame = self._frame
            options = self._console.options.update_width(width)
            panel_width = min(
                Measurement.get(self._console, options, self._view).maximum, width
            )
            panels = self._render_panels(panel_width)
        beside = width - panel_width - 1 >= MIN_SIDE_IMAGE
        cols = width - panel_width - 1 if beside else width
        rows = height if beside else height - len(panels)
        image = self._image(frame, cols, rows)
        if not beside:
            return (image + panels)[:height]
        blank = " " * cols
        return [
            (image[i] if i < len(image) else blank)
            + " "
            + (panels[i] if i < len(panels) else "")
            for i in range(height)
        ]

    def _image(self, frame: Frame | None, cols: int, rows: int) -> list[str]:
        """The image of FRAME in COLS x ROWS cells, each line padded to COLS"""
        if rows <= 0 or cols <= 0:
            return []
        image = preview_image(frame) if frame else None
        lines = render(image, self._mode, cols, rows) if image else ["waiting for frames..."]
        padded = []
        for line in lines:
            visible = len(_SGR.sub("", line))
            if visible > cols:  # a plain-text notice: a fitted image never is wider
                line, visible = line[:cols], cols
            padded.append(line + " " * (cols - visible))
        return padded

    def _render_panels(self, width: int) -> list[str]:
        buffer = io.StringIO()
        self._panels.width = width
        self._panels.file = buffer
        self._panels.print(self._view, end="")
        return buffer.getvalue().splitlines()

    def _refresh(self) -> None:
        while True:
            # an update, or time to look for a resize
            self._wake.wait(RESIZE_CHECK)
            self._wake.clear()
            started = time.monotonic()
            self._draw()
            if self._stop.wait(max(0.0, self._interval - (time.monotonic() - started))):
                return

    def _draw(self) -> None:
        size = tuple(self._console.size)
        with self._lock:
            if size == self._size and not self._changed:
                return
            self._changed = False
        clear = "\x1b[2J" if size != self._size else ""
        self._size = size
        width, height = size
        lines = self.lines(width, height)
        self._write(clear + "\x1b[H" + "\r\n".join(line + "\x1b[K" for line in lines))

    def _write(self, text: str) -> None:
        self._console.file.write(text)
        self._console.file.flush()
