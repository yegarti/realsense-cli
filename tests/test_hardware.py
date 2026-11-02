"""
Smoke tests against a connected camera, for what the software device cannot cover.
Run with `just test -m hardware`.
"""

import json
import time

import pytest
from PIL import Image
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import Realsense
from realsense_cli.types import Sensor

pytestmark = pytest.mark.hardware

runner = CliRunner()


@pytest.fixture
def camera_driver():
    driver = Realsense()
    if not driver.query_devices():
        pytest.skip("no RealSense camera connected")
    return driver


def test_pipeline_streams_defaults(camera_driver):
    camera_driver.play(pipeline=True)
    try:
        assert camera_driver.wait_for_frameset(timeout=5) is not None
    finally:
        camera_driver.stop()


def test_reset_waits_for_reconnect(camera_driver):
    assert camera_driver.reset(timeout=45)


def test_info_all_profiles(camera_driver):
    """
    A real device keeps extrinsics per stream, which the software device only imitates, and
    has profiles without intrinsics (the infrared Y16 profiles), which it can't
    """
    result = runner.invoke(app, ["--json", "info", "--all-profiles"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.stdout)
    assert info["device"]["serial_number"]
    assert info["intrinsics"]
    assert any(group["fx"] for group in info["intrinsics"])
    streams = {group["stream"] for group in info["intrinsics"]}
    pairs = {(ext["from"], ext["to"]) for ext in info["extrinsics"]}
    assert pairs == {(a, b) for a in streams for b in streams if a != b}


def test_capture_defaults(camera_driver, tmp_path):
    """
    The pipeline picks the profiles and delivers synchronized framesets, which the software
    device, streaming through the sensor API, can't
    """
    out = tmp_path / "capture"
    result = runner.invoke(app, ["--json", "capture", "--frames", "2", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["files"]) == 7
    sidecar = json.loads((out / "capture.json").read_text())
    assert sidecar["depth_scale"] > 0
    assert {p["stream"] for p in sidecar["profiles"]} == {"Depth", "Color"}
    with Image.open(out / "depth-1.png") as depth, Image.open(out / "color-1.png") as color:
        assert depth.mode == "I;16"
        assert color.mode == "RGB"
        [profile] = [p for p in sidecar["profiles"] if p["stream"] == "Depth"]
        assert depth.size == (profile["width"], profile["height"])


def test_config_get_all_while_idle(camera_driver):
    """
    A real D400 lists its temperature controls but can't read them while idle, which the
    software device can't imitate
    """
    result = runner.invoke(app, ["--json", "config", "get", "depth", "--all"])
    assert result.exit_code == 0, result.output
    values = json.loads(result.stdout)
    assert values["values"]["exposure"] > 0
    assert set(values["unavailable"]).isdisjoint(values["values"])


def _advanced_mode_off(serial: str, timeout: float = 30) -> None:
    """Turn advanced mode off on device SERIAL, which `rs` never does, and wait for it"""
    import pyrealsense2 as rs

    device = next(
        d for d in rs.context().devices if d.get_info(rs.camera_info.serial_number) == serial
    )
    try:
        rs.rs400_advanced_mode(device).toggle_advanced_mode(False)
    except RuntimeError:  # the device can reboot before it acknowledges
        pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            driver = Realsense()
            driver.active_device = serial
            if driver.advanced_mode() is False:
                return
        except Exception:  # still reconnecting
            continue
    pytest.fail(f"device '{serial}' did not come back with advanced mode off")


def test_preset_save_turns_advanced_mode_on(camera_driver, tmp_path):
    """
    The real toggle resets the device, and the real `serialize_json` writes the file. Advanced
    mode is turned off first, so this test ends with it on
    """
    serial = camera_driver.active_device
    if camera_driver.advanced_mode() is None:
        pytest.skip("the camera has no advanced mode")
    if camera_driver.advanced_mode():
        _advanced_mode_off(serial)
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["--json", "-s", serial, "preset", "save", str(path), "--yes"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["advanced_mode_enabled"] is True
    preset = json.loads(path.read_text())
    assert preset["schema version"] == 1
    assert payload["keys"] == len(preset["parameters"])
    assert "controls-laserpower" in preset["parameters"]


def test_preset_load_restores_a_saved_preset(camera_driver, tmp_path):
    """
    The real `serialize_json` -> `load_json` round trip: loading a file the device wrote
    restores what changed since. Turns advanced mode on if it's off
    """
    serial = camera_driver.active_device
    if camera_driver.advanced_mode() is None:
        pytest.skip("the camera has no advanced mode")
    path = tmp_path / "preset.json"
    cli = ["--json", "-s", serial, "preset"]
    result = runner.invoke(app, [*cli, "save", str(path), "--yes"])
    assert result.exit_code == 0, result.output
    saved = json.loads(path.read_text())["parameters"]

    # librealsense writes the laser power only with the emitter on
    if saved.get("controls-laserstate") != "on":
        pytest.skip("the emitter is off, so a load leaves the laser power alone")

    # the save may have reset the device, so find it again
    driver = Realsense()
    driver.active_device = serial
    stereo = Sensor.STEREO_MODULE
    laser = next(o for o in driver.list_controls(stereo) if o.name == "laser_power")
    power = float(saved["controls-laserpower"])
    driver.set_control_values(
        stereo,
        {"laser_power": laser.max_value if power == laser.min_value else laser.min_value},
    )
    assert json.loads(driver.serialize_preset())["parameters"] != saved

    result = runner.invoke(app, [*cli, "load", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"loaded": str(path), "advanced_mode_enabled": False}
    assert json.loads(driver.serialize_preset())["parameters"] == saved


def test_advanced_list_reads_real_ranges(camera_driver):
    """
    The real bulk read (or per-group reads before pyrealsense2 2.59), with the firmware's own
    ranges; `hdad` has none, and asking for its minimum fails. Needs advanced mode on already:
    turning it on resets the device, which `test_preset_save_turns_advanced_mode_on` covers
    """
    import pyrealsense2 as rs

    serial = camera_driver.active_device
    if not camera_driver.advanced_mode():
        pytest.skip("the camera has no advanced mode, or it's off")
    result = runner.invoke(app, ["--json", "-s", serial, "advanced", "list"])
    assert result.exit_code == 0, result.output
    controls = {c["name"]: c for c in json.loads(result.stdout)["controls"]}
    assert len(controls) == 63
    ranged = [c for c in controls.values() if c["min_value"] is not None]
    assert ranged
    assert all(c["min_value"] <= c["max_value"] for c in ranged)
    assert any(c["min_value"] < c["max_value"] for c in ranged)
    assert controls["hdad.lambdaAD"]["min_value"] is None

    result = runner.invoke(app, ["--json", "-s", serial, "advanced", "get", "--all"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["values"]) == 63

    device = next(
        d for d in rs.context().devices if d.get_info(rs.camera_info.serial_number) == serial
    )
    with pytest.raises(RuntimeError):
        rs.rs400_advanced_mode(device).get_hdad(1)


def test_advanced_set_reads_back_what_the_firmware_holds(camera_driver):
    """
    The firmware may round a float advanced control: `set` reports the value read back, which
    `get` then reads too, and moves the visual preset to custom. Puts the old value back.
    Needs advanced mode on already, as `test_advanced_list_reads_real_ranges` does
    """
    serial = camera_driver.active_device
    if not camera_driver.advanced_mode():
        pytest.skip("the camera has no advanced mode, or it's off")
    name = "rsm.diffThresh"

    def advanced(*args: str) -> dict:
        result = runner.invoke(app, ["--json", "-s", serial, "advanced", *args])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    before = advanced("get", name)["values"][name]
    try:
        # the firmware keeps diffThresh in 1/32 steps (a D455 reads 1/3 back as 0.34375)
        read_back = advanced("set", f"{name}={1 / 3}")["values"][name]
        assert read_back == advanced("get", name)["values"][name]
        assert read_back != pytest.approx(1 / 3, abs=1e-6)
        assert read_back * 32 == round(read_back * 32)
        assert read_back == pytest.approx(1 / 3, abs=1 / 32)
        preset = camera_driver.get_control_values(Sensor.STEREO_MODULE, ["visual_preset"])
        assert preset == {"visual_preset": 0}
    finally:
        advanced("set", "--no-validate", f"{name}={before}")


def test_advanced_restore_changes_laser_and_auto_exposure(camera_driver):
    """
    Writing the default visual preset sets laser on, laser power 150 and depth auto exposure
    on (`set_all()` in librealsense v2.59.1), and no other ordinary depth control. Leaves the
    camera at its Default tuning. Needs advanced mode on already, as
    `test_advanced_list_reads_real_ranges` does
    """
    serial = camera_driver.active_device
    if not camera_driver.advanced_mode():
        pytest.skip("the camera has no advanced mode, or it's off")
    camera_driver.set_control_values(
        Sensor.STEREO_MODULE,
        {"laser_power": 90, "emitter_enabled": 0, "enable_auto_exposure": 0},
    )

    result = runner.invoke(app, ["--json", "-s", serial, "advanced", "restore"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["failed"] == []
    changed = {row["control"]: (row["old"], row["new"]) for row in payload["restored"]}
    assert changed.pop("visual_preset")[1] == 1.0
    assert changed == {
        "emitter_enabled": (0.0, 1.0),
        "laser_power": (90.0, 150.0),
        "enable_auto_exposure": (0.0, 1.0),
    }


def test_bag_record_defaults(camera_driver, tmp_path):
    """
    The recorder wraps a real device, whose UVC sensors it records through the same hooks as
    the software device's. Depth only: an uncompressed color stream can stall for over 3
    seconds on a slow link, such as USB/IP
    """
    path = tmp_path / "run.db3"
    result = runner.invoke(
        app, ["--json", "bag", "record", "depth", "--frames", "10", "-o", str(path)]
    )
    assert result.exit_code == 0, result.output
    recorded = json.loads(result.stdout)
    assert recorded["size"] == path.stat().st_size > 0
    assert all(stream["frames"] >= 10 for stream in recorded["streams"])

    result = runner.invoke(app, ["--json", "bag", "info", str(path)])
    assert result.exit_code == 0, result.output
    frames = {
        (s["stream"], s["index"]): s["frames"] for s in json.loads(result.stdout)["streams"]
    }
    assert frames == {(s["stream"], s["index"]): s["frames"] for s in recorded["streams"]}
