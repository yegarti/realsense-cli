import pytest
from realsense_cli.driver.realsense import Realsense
from tests.utils import MOCK_DEVICE, MOCK_SENSORS

pytestmark = pytest.mark.hardware


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


def test_list_controls(mock_context, driver):
    result = {opt.name: opt for opt in driver.list_controls("Stereo Module")}
    expected = MOCK_SENSORS["options"]["Stereo Module"]
    for option in expected:
        assert option.name in result
        opt_res = result[option.name]
        assert option.min_value == pytest.approx(opt_res.min_value)
        assert option.max_value == pytest.approx(opt_res.max_value)
        assert option.default_value == pytest.approx(opt_res.default_value)
        assert option.step == pytest.approx(opt_res.step)


def test_get_control_values(mock_context, driver):
    data = MOCK_SENSORS["options"]["Stereo Module"]
    opts = [option.name for option in data]
    result = driver.get_control_values("Stereo Module", opts)

    for opt in data:
        assert opt.name in result
        assert result[opt.name] == pytest.approx(opt.default_value)


def test_set_control_values(mock_context, driver):
    data = MOCK_SENSORS["options"]["Stereo Module"]
    driver.set_control_values(
        "Stereo Module",
        {
            "exposure": 1000,
        },
    )
    opts = [option.name for option in data]
    result = driver.get_control_values("Stereo Module", opts)

    for opt in data:
        assert opt.name in result
        if opt.name == "exposure":
            assert result["exposure"] == pytest.approx(1000.0)
        else:
            assert result[opt.name] == pytest.approx(opt.default_value)


def test_list_streams(mock_context, driver):
    data = MOCK_SENSORS["profiles"]["Stereo Module"]
    result = driver.list_streams("Stereo Module")
    assert len(data) == len(result)
    for profile in data:
        assert profile in result
