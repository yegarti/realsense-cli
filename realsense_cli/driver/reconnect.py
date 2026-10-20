"""
Following a device through a hardware reset by its device-changed events: it drops off, then
comes back as a new device with the same serial.
"""

import threading
import time
from collections.abc import Callable


class ReconnectWatch:
    """
    Device-changed events for device SERIAL. Feed it from the SDK callback, registered before
    the reset is sent so the `removed` event can't be missed
    """

    def __init__(self, serial: str):
        self.serial = serial
        self.removed = threading.Event()
        self.added = threading.Event()

    def on_removed(self, serial: str) -> None:
        if serial == self.serial:
            self.removed.set()

    def on_added(self, serial: str) -> None:
        # an `added` before the drop is the device from before the reset
        if serial == self.serial and self.removed.is_set():
            self.added.set()


def reset_and_wait(
    watch: ReconnectWatch,
    reset: Callable[[], None],
    ready: Callable[[], bool],
    timeout: float | None = None,
    ack_grace: float = 10,
    poll: float = 0.1,
) -> bool:
    """
    Send the hardware RESET, then wait up to TIMEOUT seconds for WATCH's device to come back
    and be READY to answer. Without TIMEOUT it doesn't wait. Whether the device is back

    The device can reboot before it acknowledges the reset, and the SDK then raises; that
    counts as a reset when the device drops off within ACK_GRACE seconds
    """
    try:
        reset()
    except RuntimeError:
        if not watch.removed.wait(ack_grace):
            raise
    if timeout is None:
        return True
    deadline = time.monotonic() + timeout
    if not watch.added.wait(timeout):
        return False
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(poll)
    return False
