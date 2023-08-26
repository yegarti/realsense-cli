from dataclasses import dataclass
from typing import Optional

from rich.console import RenderableType, Group
from rich.panel import Panel

from realsense_cli.model import Stream, FrameSet, Frame, Profile


class StreamView(Group):
    def __init__(self, streams: list[Stream]):
        self._panels: dict[Stream, Panel] = {
            stream: Panel('...', title=stream.value, width=45) for stream in streams
        }
        super().__init__(*self._panels.values())
        self._title_set = dict.fromkeys(self._panels, False)
        self._prev_frame: dict[Stream, Frame] = dict.fromkeys(streams, None)

    def update(self, frames: Optional[FrameSet]):
        for stream, frame in frames.items():
            if stream not in self._panels:
                continue
            profile = frame.profile
            if not self._title_set[stream]:
                self._panels[stream].title = self._gen_panel_title(profile)
                self._title_set[stream] = True

            metrics = {
                'index': frame.index,
                'fps': self._calc_fps(frame)
            }
            self._panels[stream].renderable = f"Frame #{metrics['index']:<8} FPS: {metrics['fps']:<4.2f}"

    @property
    def panels(self):
        return self._panels

    def _gen_panel_title(self, profile: Profile) -> str:
        return '{stream} ({index}) {width}x{height} {fps}fps {format}'.format(
            stream=profile.stream.value,
            index=profile.index,
            width=profile.resolution.width,
            height=profile.resolution.height,
            format=profile.format,
            fps=profile.fps
        )

    def _calc_fps(self, frame: Frame) -> float:
        stream = frame.profile.stream
        prev_frame = self._prev_frame[stream]
        if not prev_frame:
            self._prev_frame[stream] = frame
            return 0
        num = frame.index - prev_frame.index
        delta = frame.timestamp - prev_frame.timestamp
        if not delta:
            return 0

        return 1000 * (num / delta)
