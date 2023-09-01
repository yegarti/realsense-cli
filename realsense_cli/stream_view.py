from dataclasses import dataclass
from typing import Optional, Any

from loguru import logger
from rich.box import SIMPLE, SIMPLE_HEAD
from rich.console import RenderableType, Group, group
from rich.panel import Panel

from realsense_cli.types import Stream, FrameSet, Frame, Profile


class StreamView(Panel):
    def __init__(self, streams: Optional[list[Stream]] = None):
        logger.info("StreamView created")
        self._dynamic = not streams
        self._panels: dict[Stream, Panel] = {}
        self._title_set: dict[Stream, bool] = {}
        self._prev_frame: dict[Stream, Optional[Frame]] = {}
        self._regroup(streams)

        super().__init__(Group(*self._panels.values()), box=SIMPLE_HEAD, title_align="center")

    def update(self, frames: Optional[FrameSet]):
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
            self._panels[
                stream
            ].renderable = f"Frame #{metrics['index']:<8} FPS: {metrics['fps']:<4.2f}"

    def _regroup(self, streams: Optional[list[Stream]]):
        logger.info("Regroup for streams {}", streams)
        if not streams:
            streams = []
        for stream in streams:
            panel = Panel("...", title=stream.value, width=45)
            self._panels[stream] = panel
            self._title_set[stream] = False
            self._prev_frame[stream] = None

        self.renderable = Group(*self._panels.values())

    @property
    def panels(self):
        return self._panels

    def _gen_panel_title(self, profile: Profile) -> str:
        return "{stream} ({index}) {width}x{height} {fps}fps {format}".format(
            stream=profile.stream.value,
            index=profile.index,
            width=profile.resolution.width,
            height=profile.resolution.height,
            format=profile.format,
            fps=profile.fps,
        )

    def _calc_fps(self, frame: Frame) -> float:
        stream = frame.profile.stream
        prev_frame = self._prev_frame[stream]
        if not prev_frame:
            self._prev_frame[stream] = frame
            return 0
        num = frame.index - prev_frame.index
        delta = frame.timestamp - prev_frame.timestamp
        logger.debug(
            "calc fps {} - num = {}, delta = {}", frame.profile.stream.name, num, delta
        )
        self._prev_frame[stream] = frame
        if not delta:
            return 0

        return 1000 * (num / delta)
