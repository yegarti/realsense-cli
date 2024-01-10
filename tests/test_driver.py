import pytest
from realsense_cli.driver import Realsense
from realsense_cli.types import Sensor
from tests.utils import MOCK_DEVICE, MOCK_SENSORS


@pytest.fixture
def driver():
    yield Realsense()


def test_query_devices_single_device(mock_context, driver):
    devices = driver.query_devices()
    assert len(devices) == 1
    assert devices[0] == MOCK_DEVICE


def test_query_devices_no_device(driver):
    devices = driver.query_devices()
    assert len(devices) == 0


# @pytest.mark.parametrize('sensor')
def test_list_controls(mock_context, driver):
    result = {opt.name: opt for opt in driver.list_controls(Sensor.STEREO_MODULE)}
    expected = MOCK_SENSORS["options"][Sensor.STEREO_MODULE]
    for option in expected:
        assert option.name in result
        opt_res = result[option.name]
        assert option.min_value == pytest.approx(opt_res.min_value)
        assert option.max_value == pytest.approx(opt_res.max_value)
        assert option.default_value == pytest.approx(opt_res.default_value)
        assert option.step == pytest.approx(opt_res.step)


def test_get_control_values(mock_context, driver):
    data = MOCK_SENSORS["options"][Sensor.STEREO_MODULE]
    opts = [option.name for option in data]
    result = driver.get_control_values(Sensor.STEREO_MODULE, opts)

    for opt in data:
        assert opt.name in result
        assert result[opt.name] == pytest.approx(opt.default_value)


def test_set_control_values(mock_context, driver):
    data = MOCK_SENSORS["options"][Sensor.STEREO_MODULE]
    driver.set_control_values(
        Sensor.STEREO_MODULE,
        {
            "exposure": 1000,
        },
    )
    opts = [option.name for option in data]
    result = driver.get_control_values(Sensor.STEREO_MODULE, opts)

    for opt in data:
        assert opt.name in result
        if opt.name == "exposure":
            assert result["exposure"] == pytest.approx(1000.0)
        else:
            assert result[opt.name] == pytest.approx(opt.default_value)


def test_list_streams(mock_context, driver):
    data = MOCK_SENSORS["profiles"][Sensor.STEREO_MODULE]
    result = driver.list_streams(Sensor.STEREO_MODULE)
    assert len(data) == len(result)
    for profile in data:
        assert profile in result
