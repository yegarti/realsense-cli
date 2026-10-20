import json

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435

runner = CliRunner()


@pytest.fixture
def resets(monkeypatch, two_cameras):
    """Serials the stubbed hardware reset was sent to; a software device can't reset."""
    calls = []
    monkeypatch.setattr(two_cameras, "reset", lambda: calls.append(two_cameras.active_device))
    return calls


def test_ambiguous_device_without_tty_fails(resets):
    result = runner.invoke(app, ["reset"])
    assert result.exit_code == 8, result.output
    assert "--serial" in result.stderr
    assert "--yes" in result.stderr
    assert resets == []


def test_ambiguous_device_under_json_fails(resets):
    result = runner.invoke(app, ["--json", "reset"])
    assert result.exit_code == 8, result.output
    error = json.loads(result.stderr.splitlines()[-1])["error"]
    assert error["type"] == "ConfirmationRequired"
    assert resets == []


def test_serial_resets_without_prompt(resets):
    result = runner.invoke(app, ["--serial", "987654321", "reset"])
    assert result.exit_code == 0, result.output
    assert resets == ["987654321"]


def test_yes_resets_without_prompt(resets):
    result = runner.invoke(app, ["reset", "--yes"])
    assert result.exit_code == 0, result.output
    assert resets == [D435.serial]


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr("realsense_cli.session._stdin_is_tty", lambda: True)


def test_ambiguous_device_on_tty_prompts(resets, tty):
    result = runner.invoke(app, ["reset"], input="y\n")
    assert result.exit_code == 0, result.output
    assert f"Reset {D435.name} ({D435.serial})?" in result.stderr
    assert resets == [D435.serial]


def test_declined_prompt_aborts(resets, tty):
    result = runner.invoke(app, ["reset"], input="n\n")
    assert result.exit_code == 1, result.output
    assert resets == []


def test_json_never_prompts_even_on_tty(resets, tty):
    result = runner.invoke(app, ["--json", "reset"])
    assert result.exit_code == 8, result.output
    assert resets == []


def test_single_device_on_tty_resets_without_prompt(driver, monkeypatch, tty):
    calls = []
    monkeypatch.setattr(driver, "reset", lambda: calls.append(True))
    result = runner.invoke(app, ["reset"])
    assert result.exit_code == 0, result.output
    assert "?" not in result.stderr
    assert calls == [True]


@pytest.fixture
def reconnects(monkeypatch, driver):
    """Stub the hardware reset, and record each wait's timeout; the device comes back."""
    waits = []
    monkeypatch.setattr(driver, "reset", lambda: None)
    monkeypatch.setattr(
        driver,
        "wait_for_reconnect",
        lambda serial, timeout: waits.append((serial, timeout)) or True,
    )
    return waits


def test_wait_reports_reconnect(reconnects):
    result = runner.invoke(app, ["--json", "reset", "--wait", "--timeout", "5"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"reset": D435.serial, "reconnected": True}
    assert reconnects == [(D435.serial, 5)]


def test_wait_timeout_fails(driver, monkeypatch):
    monkeypatch.setattr(driver, "reset", lambda: None)
    monkeypatch.setattr(driver, "wait_for_reconnect", lambda serial, timeout: False)
    result = runner.invoke(app, ["reset", "--wait"])
    assert result.exit_code == 3, result.output
    assert D435.serial in result.stderr


def test_without_wait_doesnt_wait(reconnects):
    result = runner.invoke(app, ["--json", "reset"])
    assert json.loads(result.stdout) == {"reset": D435.serial}
    assert reconnects == []
