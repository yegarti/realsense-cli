import pytest

from realsense_cli.driver.reconnect import ReconnectWatch, reset_and_wait

SERIAL = "1"


def send(watch: ReconnectWatch, *events: tuple[str, str], error: str | None = None):
    """A hardware reset that fires EVENTS, as (removed|added, serial), then maybe raises."""

    def reset() -> None:
        for kind, serial in events:
            getattr(watch, f"on_{kind}")(serial)
        if error:
            raise RuntimeError(error)

    return reset


def run(watch, reset, ready=lambda: True, timeout: float | None = 1, ack_grace: float = 0.05):
    return reset_and_wait(watch, reset, ready, timeout=timeout, ack_grace=ack_grace, poll=0.001)


@pytest.fixture
def watch() -> ReconnectWatch:
    return ReconnectWatch(SERIAL)


def test_device_drops_returns_and_answers(watch):
    assert run(watch, send(watch, ("removed", SERIAL), ("added", SERIAL)))


def test_without_timeout_does_not_wait_for_the_device(watch):
    assert run(watch, send(watch), timeout=None)


def test_unacknowledged_reset_counts_when_the_device_drops(watch):
    """The device can reboot before acknowledging the command, so the SDK raises."""
    reset = send(watch, ("removed", SERIAL), error="xioctl: Timer expired")
    assert run(watch, reset, timeout=None)


def test_unacknowledged_reset_without_a_drop_raises(watch):
    with pytest.raises(RuntimeError, match="Timer expired"):
        run(watch, send(watch, error="xioctl: Timer expired"), timeout=None)


def test_device_that_never_returns_times_out(watch):
    assert not run(watch, send(watch, ("removed", SERIAL)), timeout=0.05)


def test_added_before_removed_is_not_a_reconnect(watch):
    """An `added` with no `removed` before it is the device from before the reset."""
    assert not run(watch, send(watch, ("added", SERIAL)), timeout=0.05)


def test_other_devices_events_are_ignored(watch):
    reset = send(watch, ("removed", "2"), ("added", "2"), ("removed", SERIAL))
    assert not run(watch, reset, timeout=0.05)


def test_device_that_returns_but_never_answers_times_out(watch):
    reset = send(watch, ("removed", SERIAL), ("added", SERIAL))
    assert not run(watch, reset, ready=lambda: False, timeout=0.05)
