from loguru import logger
from rich.box import SIMPLE_HEAD
from rich.console import Group
from rich.panel import Panel

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
