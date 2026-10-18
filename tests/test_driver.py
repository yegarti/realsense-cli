import pytest

from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435, d435_sensor

STEREO = d435_sensor("Stereo Module")


def test_query_devices_single_device(driver):
    assert driver.query_devices() == [D435]


def test_query_devices_no_device():
    assert Realsense(devices=[]).query_devices() == []


def test_list_controls(driver):
    result = {opt.name: opt for opt in driver.list_controls(STEREO.name)}
    for option in STEREO.options:
        assert option.name in result
        opt_res = result[option.name]
        assert opt_res.min_value == pytest.approx(option.min_value)
        assert opt_res.max_value == pytest.approx(option.max_value)
        assert opt_res.default_value == pytest.approx(option.default_value)
        assert opt_res.step == pytest.approx(option.step)
        assert opt_res.vtype is option.vtype


def test_get_control_values(driver):
    result = driver.get_control_values(STEREO.name, [opt.name for opt in STEREO.options])
    for opt in STEREO.options:
        assert result[opt.name] == pytest.approx(opt.default_value)


def test_set_control_values(driver):
    driver.set_control_values(STEREO.name, {"exposure": 1000})
    result = driver.get_control_values(STEREO.name, [opt.name for opt in STEREO.options])
    for opt in STEREO.options:
        expected = 1000.0 if opt.name == "exposure" else opt.default_value
        assert result[opt.name] == pytest.approx(expected)


def test_get_unsupported_control(driver):
    with pytest.raises(ValueError, match="not supported"):
        driver.get_control_values(STEREO.name, ["gain"])


def test_list_streams(driver):
    def key(p):
        return (p.stream, p.resolution, p.fps, p.format.upper(), p.index)

    result = driver.list_streams(STEREO.name)
    assert sorted(map(key, result)) == sorted(map(key, STEREO.profiles))


def test_stream_motion(driver, camera):
    driver.play([d435_sensor("Motion Module").profiles[0]], pipeline=False)
    try:
        camera.push_frames()
        frameset = driver.wait_for_frameset()
        assert frameset is not None
        assert list(frameset) == ["Gyro"]
    finally:
        driver.stop()


def test_play_without_profiles_streams_defaults(driver, camera):
    driver.play()
    try:
        active = {
            (p.stream_name(), p.fps())
            for sensor in camera.device.sensors
            for p in sensor.get_active_streams()
        }
        assert active == {
            ("Depth", 30),
            ("Infrared 1", 30),
            ("Infrared 2", 30),
            ("Color", 30),
            ("Gyro", 200),
            ("Accel", 63),
        }
        camera.push_frames()
        assert driver.wait_for_frameset() is not None
    finally:
        driver.stop()
