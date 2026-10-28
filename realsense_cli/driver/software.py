"""
Simulated cameras built on `rs.software_device`.

The software device runs through the real `Realsense` driver code, so tests exercise the same
pyrealsense2 calls as production. It produces no frames on its own: call
`SoftwareCamera.push_frames()` to feed every active stream one frame, or
`start_frame_pump()` to keep feeding them from a background thread.

The last profile listed for each stream in a `SensorSpec` is that stream's default.

Z16 frames hold a known depth pattern (`depth_pixels()`); every other stream a byte ramp
(`pixels()`).

A camera can have advanced mode (`FakeAdvancedMode`), which `software_driver()` serves to the
driver: pyrealsense2 has none for a software device.

A software device keeps extrinsics per profile, where a real device keeps them per stream: each
stream's profiles are linked to each other, so extrinsics registered between two streams reach
every profile of both.
"""

import json
import threading
import time
from array import array
from collections.abc import Collection
from dataclasses import dataclass, field
from itertools import count
from typing import NamedTuple

import pyrealsense2 as rs

from realsense_cli.driver.realsense import AdvancedMode, Realsense
from realsense_cli.types import (
    DeviceInfo,
    Extrinsics,
    Intrinsics,
    Option,
    Profile,
    Resolution,
    Sensor,
    Stream,
)

_BYTES_PER_PIXEL: dict[str, int] = {"z16": 2, "y8": 1, "rgb8": 3, "bgr8": 3, "yuyv": 2}


@dataclass
class SensorSpec:
    name: str
    profiles: list[Profile]
    options: list[Option] = field(default_factory=list)
    read_only_options: dict[str, float] = field(default_factory=dict)
    intrinsics: dict[str, Intrinsics] = field(default_factory=dict)  # keyed by stream name


class SoftwareCamera:
    def __init__(
        self,
        info: DeviceInfo,
        sensors: list[SensorSpec],
        camera_info: dict[str, str] | None = None,
        extrinsics: list[Extrinsics] | None = None,
        advanced_mode: bool | None = None,
    ):
        """
        CAMERA_INFO registers more camera info fields on top of those INFO holds, keyed by
        their `rs.camera_info` name. EXTRINSICS are registered between the streams they name.
        ADVANCED_MODE gives the camera a `FakeAdvancedMode` that starts on (True) or off
        (False); without it the camera has no advanced mode
        """
        self.info = info
        self.device = rs.software_device()
        # pyrealsense2 < 2.55 pre-registers a name, and registering again appends to it
        if self.device.supports(rs.camera_info.name):
            self.device.update_info(rs.camera_info.name, info.name)
        else:
            self.device.register_info(rs.camera_info.name, info.name)
        self.device.register_info(rs.camera_info.serial_number, info.serial)
        self.device.register_info(rs.camera_info.firmware_version, info.fw)
        self.device.register_info(rs.camera_info.usb_type_descriptor, info.connection)
        # fields the installed SDK doesn't know, such as imu_type on 2.56, are left out
        for name, value in (camera_info or {}).items():
            if name in rs.camera_info.__members__:
                self.device.register_info(rs.camera_info.__members__[name], value)

        self._sensors: list[rs.software_sensor] = []
        self._frame_numbers = count()
        uid = count()
        stream_profiles: dict[str, list[rs.stream_profile]] = {}
        for spec in sensors:
            sensor = self.device.add_sensor(spec.name)
            self._sensors.append(sensor)
            defaults = {p.stream: p for p in spec.profiles}
            for profile in spec.profiles:
                rs_profile = _add_stream(
                    sensor,
                    profile,
                    next(uid),
                    defaults[profile.stream] is profile,
                    spec.intrinsics.get(profile.stream),
                )
                stream_profiles.setdefault(profile.stream, []).append(rs_profile)
            for option in spec.options:
                rng = _option_range(
                    option.min_value, option.max_value, option.step, option.default_value
                )
                sensor.add_option(getattr(rs.option, option.name), rng, True)
            for name, value in spec.read_only_options.items():
                sensor.add_read_only_option(getattr(rs.option, name), value)

        for first, *others in stream_profiles.values():
            for other in others:
                first.register_extrinsics_to(other, _rs_extrinsics(_IDENTITY, (0, 0, 0)))
        for ext in extrinsics or []:
            source, target = stream_profiles[ext.source][0], stream_profiles[ext.target][0]
            source.register_extrinsics_to(target, _rs_extrinsics(ext.rotation, ext.translation))

        self.advanced_mode: FakeAdvancedMode | None = None
        if advanced_mode is not None:
            self.advanced_mode = FakeAdvancedMode(self, advanced_mode)

    def sensor(self, name: str) -> rs.software_sensor:
        return next(sensor for sensor in self._sensors if sensor.name == name)

    def start_frame_pump(self, fps: int = 30) -> None:
        """Push frames to active streams at FPS from a daemon thread until exit."""

        def pump():
            while True:
                self.push_frames()
                time.sleep(1 / fps)

        threading.Thread(target=pump, name="software-camera-pump", daemon=True).start()

    def push_frames(self, streams: Collection[str] | None = None) -> None:
        """
        Push one frame to every stream currently started on the device, or only to those
        named in STREAMS
        """
        frame_number = next(self._frame_numbers)
        timestamp = frame_number * 1000 / 30
        for sensor in self._sensors:
            for profile in sensor.get_active_streams():
                if streams is not None and profile.stream_name() not in streams:
                    continue
                if profile.is_motion_stream_profile():
                    motion = rs.software_motion_frame()
                    motion.data = rs.vector()
                    motion.profile = profile.as_motion_stream_profile()
                    motion.frame_number = frame_number
                    motion.timestamp = timestamp
                    motion.domain = rs.timestamp_domain.hardware_clock
                    sensor.on_motion_frame(motion)
                else:
                    vsp = profile.as_video_stream_profile()
                    fmt = vsp.format().name
                    bpp = _BYTES_PER_PIXEL[fmt]
                    video = rs.software_video_frame()
                    if fmt == "z16":
                        data = depth_pixels(vsp.width(), vsp.height(), frame_number)
                    else:
                        data = pixels(vsp.width() * vsp.height() * bpp, frame_number)
                    video.pixels = bytearray(data)
                    video.bpp = bpp
                    video.stride = vsp.width() * bpp
                    video.profile = vsp
                    video.frame_number = frame_number
                    video.timestamp = timestamp
                    video.domain = rs.timestamp_domain.hardware_clock
                    sensor.on_video_frame(video)


# The advanced-mode group structs, by the group names `rs.rs400_advanced_mode.keys()` lists
_GROUPS: dict[str, type["rs._AdvancedModeGroup"]] = {
    "depth_control": rs.STDepthControlGroup,
    "rsm": rs.STRsm,
    "rau_support_vector_control": rs.STRauSupportVectorControl,
    "color_control": rs.STColorControl,
    "rau_thresholds_control": rs.STRauColorThresholdsControl,
    "slo_color_thresholds_control": rs.STSloColorThresholdsControl,
    "slo_penalty_control": rs.STSloPenaltyControl,
    "hdad": rs.STHdad,
    "color_correction": rs.STColorCorrection,
    "depth_table": rs.STDepthTableControl,
    "ae_control": rs.STAEControl,
    "census": rs.STCensusRadius,
    "amp_factor": rs.STAFactor,
}

# librealsense's D435 Default tuning in struct units (`default_430()` in presets.cpp, v2.59.1)
D435_DEFAULT_TUNING: dict[str, dict[str, float]] = {
    "depth_control": {
        "plusIncrement": 10,
        "minusDecrement": 10,
        "deepSeaMedianThreshold": 500,
        "scoreThreshA": 1,
        "scoreThreshB": 2047,
        "textureDifferenceThreshold": 0,
        "textureCountThreshold": 0,
        "deepSeaSecondPeakThreshold": 325,
        "deepSeaNeighborThreshold": 7,
        "lrAgreeThreshold": 24,
    },
    "rsm": {"rsmBypass": 0, "diffThresh": 4.0, "sloRauDiffThresh": 1.0, "removeThresh": 63},
    "rau_support_vector_control": {
        "minWest": 1,
        "minEast": 1,
        "minWEsum": 3,
        "minNorth": 1,
        "minSouth": 1,
        "minNSsum": 3,
        "uShrink": 3,
        "vShrink": 1,
    },
    "color_control": dict.fromkeys(
        (
            "disableSADColor",
            "disableRAUColor",
            "disableSLORightColor",
            "disableSLOLeftColor",
            "disableSADNormalize",
        ),
        0,
    ),
    "rau_thresholds_control": dict.fromkeys(
        ("rauDiffThresholdRed", "rauDiffThresholdGreen", "rauDiffThresholdBlue"), 51
    ),
    "slo_color_thresholds_control": dict.fromkeys(
        ("diffThresholdRed", "diffThresholdGreen", "diffThresholdBlue"), 72
    ),
    "slo_penalty_control": {
        "sloK1Penalty": 60,
        "sloK2Penalty": 342,
        "sloK1PenaltyMod1": 105,
        "sloK2PenaltyMod1": 190,
        "sloK1PenaltyMod2": 70,
        "sloK2PenaltyMod2": 130,
    },
    "hdad": {"lambdaCensus": 26.0, "lambdaAD": 800.0, "ignoreSAD": 0},
    "color_correction": {
        "colorCorrection1": 0.298828,
        "colorCorrection2": 0.293945,
        "colorCorrection3": 0.293945,
        "colorCorrection4": 0.114258,
        **{f"colorCorrection{i}": 0.0 for i in range(5, 13)},
    },
    "depth_table": {
        "depthUnits": 1000,
        "depthClampMin": 0,
        "depthClampMax": 65536,
        "disparityMode": 0,
        "disparityShift": 0,
    },
    "ae_control": {"meanIntensitySetPoint": 1536},
    "census": {"uDiameter": 9, "vDiameter": 9},
    "amp_factor": {"a_factor": 0.0},
}

# The preset keys librealsense writes for advanced controls, -> (group, field, scale): the file
# holds the field's value divided by the scale (`initialize_field_parsers()` in json_loader.hpp,
# v2.59.1). It leaves out the ignored keys and the read-only `param-colorcorrection*` duplicates
_PRESET_KEYS: dict[str, tuple[str, str, float]] = {
    "param-leftrightthreshold": ("depth_control", "lrAgreeThreshold", 1),
    "param-maxscorethreshb": ("depth_control", "scoreThreshB", 1),
    "param-medianthreshold": ("depth_control", "deepSeaMedianThreshold", 1),
    "param-minscorethresha": ("depth_control", "scoreThreshA", 1),
    "param-texturedifferencethresh": ("depth_control", "textureDifferenceThreshold", 1),
    "param-neighborthresh": ("depth_control", "deepSeaNeighborThreshold", 1),
    "param-secondpeakdelta": ("depth_control", "deepSeaSecondPeakThreshold", 1),
    "param-texturecountthresh": ("depth_control", "textureCountThreshold", 1),
    "param-robbinsmonrodecrement": ("depth_control", "minusDecrement", 1),
    "param-robbinsmonroincrement": ("depth_control", "plusIncrement", 1),
    "param-usersm": ("rsm", "rsmBypass", 1),  # inverted: 1 when rsmBypass is 0
    "param-rsmdiffthreshold": ("rsm", "diffThresh", 1),
    "param-rsmrauslodiffthreshold": ("rsm", "sloRauDiffThresh", 1),
    "param-rsmremovethreshold": ("rsm", "removeThresh", 168),
    "param-raumine": ("rau_support_vector_control", "minEast", 1),
    "param-rauminn": ("rau_support_vector_control", "minNorth", 1),
    "param-rauminnssum": ("rau_support_vector_control", "minNSsum", 1),
    "param-raumins": ("rau_support_vector_control", "minSouth", 1),
    "param-rauminw": ("rau_support_vector_control", "minWest", 1),
    "param-rauminwesum": ("rau_support_vector_control", "minWEsum", 1),
    "param-regionshrinku": ("rau_support_vector_control", "uShrink", 1),
    "param-regionshrinkv": ("rau_support_vector_control", "vShrink", 1),
    "param-disableraucolor": ("color_control", "disableRAUColor", 1),
    "param-disablesadcolor": ("color_control", "disableSADColor", 1),
    "param-disablesadnormalize": ("color_control", "disableSADNormalize", 1),
    "param-disablesloleftcolor": ("color_control", "disableSLOLeftColor", 1),
    "param-disableslorightcolor": ("color_control", "disableSLORightColor", 1),
    "param-regioncolorthresholdb": ("rau_thresholds_control", "rauDiffThresholdBlue", 1022),
    "param-regioncolorthresholdg": ("rau_thresholds_control", "rauDiffThresholdGreen", 1022),
    "param-regioncolorthresholdr": ("rau_thresholds_control", "rauDiffThresholdRed", 1022),
    "param-scanlineedgetaub": ("slo_color_thresholds_control", "diffThresholdBlue", 1),
    "param-scanlineedgetaug": ("slo_color_thresholds_control", "diffThresholdGreen", 1),
    "param-scanlineedgetaur": ("slo_color_thresholds_control", "diffThresholdRed", 1),
    "param-scanlinep1": ("slo_penalty_control", "sloK1Penalty", 1),
    "param-scanlinep1onediscon": ("slo_penalty_control", "sloK1PenaltyMod1", 1),
    "param-scanlinep1twodiscon": ("slo_penalty_control", "sloK1PenaltyMod2", 1),
    "param-scanlinep2": ("slo_penalty_control", "sloK2Penalty", 1),
    "param-scanlinep2onediscon": ("slo_penalty_control", "sloK2PenaltyMod1", 1),
    "param-scanlinep2twodiscon": ("slo_penalty_control", "sloK2PenaltyMod2", 1),
    "param-lambdaad": ("hdad", "lambdaAD", 1),
    "param-lambdacensus": ("hdad", "lambdaCensus", 1),
    "ignoreSAD": ("hdad", "ignoreSAD", 1),
    **{
        f"aux-param-colorcorrection{i}": ("color_correction", f"colorCorrection{i}", 1)
        for i in range(1, 13)
    },
    "param-depthunits": ("depth_table", "depthUnits", 1),
    "param-zunits": ("depth_table", "depthUnits", 1),
    "param-depthclampmin": ("depth_table", "depthClampMin", 1),
    "param-depthclampmax": ("depth_table", "depthClampMax", 1),
    "aux-param-depthclampmin": ("depth_table", "depthClampMin", 1),
    "aux-param-depthclampmax": ("depth_table", "depthClampMax", 1),
    "param-disparitymode": ("depth_table", "disparityMode", 1),
    "param-disparityshift": ("depth_table", "disparityShift", 1),
    "aux-param-disparityshift": ("depth_table", "disparityShift", 1),
    "param-autoexposure-setpoint": ("ae_control", "meanIntensitySetPoint", 1),
    "aux-param-autoexposure-setpoint": ("ae_control", "meanIntensitySetPoint", 1),
    "param-censusenablereg-udiameter": ("census", "uDiameter", 1),
    "param-censusenablereg-vdiameter": ("census", "vDiameter", 1),
    "param-censususize": ("census", "uDiameter", 1),
    "param-censusvsize": ("census", "vDiameter", 1),
    "param-amplitude-factor": ("amp_factor", "a_factor", 1),
}

_AUTO = {0: "False", 1: "True"}

# The preset keys librealsense writes for controls, when the sensor has the control:
# key -> (sensor, control, the names it writes for the control's values, if any)
_PRESET_CONTROLS: dict[str, tuple[str, str, dict[float, str] | None]] = {
    "controls-laserstate": (
        Sensor.STEREO_MODULE,
        "emitter_enabled",
        {0: "off", 1: "on", 2: "auto"},
    ),
    "controls-laserpower": (Sensor.STEREO_MODULE, "laser_power", None),
    "controls-autoexposure-manual": (Sensor.STEREO_MODULE, "exposure", None),
    "controls-autoexposure-auto": (Sensor.STEREO_MODULE, "enable_auto_exposure", _AUTO),
    "controls-depth-gain": (Sensor.STEREO_MODULE, "gain", None),
    "controls-depth-white-balance-auto": (
        Sensor.STEREO_MODULE,
        "enable_auto_white_balance",
        _AUTO,
    ),
    "controls-color-autoexposure-manual": (Sensor.RGB_CAMERA, "exposure", None),
    "controls-color-autoexposure-auto": (Sensor.RGB_CAMERA, "enable_auto_exposure", _AUTO),
    "controls-color-backlight-compensation": (
        Sensor.RGB_CAMERA,
        "backlight_compensation",
        None,
    ),
    "controls-color-brightness": (Sensor.RGB_CAMERA, "brightness", None),
    "controls-color-contrast": (Sensor.RGB_CAMERA, "contrast", None),
    "controls-color-gain": (Sensor.RGB_CAMERA, "gain", None),
    "controls-color-gamma": (Sensor.RGB_CAMERA, "gamma", None),
    "controls-color-hue": (Sensor.RGB_CAMERA, "hue", None),
    "controls-color-saturation": (Sensor.RGB_CAMERA, "saturation", None),
    "controls-color-sharpness": (Sensor.RGB_CAMERA, "sharpness", None),
    "controls-color-power-line-frequency": (Sensor.RGB_CAMERA, "power_line_frequency", None),
    "controls-color-white-balance-manual": (Sensor.RGB_CAMERA, "white_balance", None),
    "controls-color-white-balance-auto": (
        Sensor.RGB_CAMERA,
        "enable_auto_white_balance",
        _AUTO,
    ),
}


class FakeAdvancedMode:
    """
    Advanced mode for a SoftwareCamera: the part of `rs.rs400_advanced_mode` the driver calls,
    which pyrealsense2 can't give a software device. It holds the D435 Default tuning in real
    pyrealsense2 group structs.

    As on a D400, the depth sensor has `visual_preset` and a writable `depth_units` only while
    advanced mode is on, and `camera_info.advanced_mode` says whether it is. Turning it on
    doesn't reset the camera. It can't be turned off: a software sensor can't drop an option
    """

    def __init__(self, camera: SoftwareCamera, enabled: bool):
        self._camera = camera
        self._enabled = enabled
        self.groups = {name: struct() for name, struct in _GROUPS.items()}
        for name, fields in D435_DEFAULT_TUNING.items():
            for field_name, value in fields.items():
                self.groups[name][field_name] = value
        depth = camera.sensor(Sensor.STEREO_MODULE)
        self._depth_units = depth.get_option_range(rs.option.depth_units)
        camera.device.register_info(rs.camera_info.advanced_mode, "YES" if enabled else "NO")
        if enabled:
            self._add_options()
        else:
            depth.add_read_only_option(rs.option.depth_units, self._depth_units.default)

    def _add_options(self) -> None:
        depth = self._camera.sensor(Sensor.STEREO_MODULE)
        depth.add_option(rs.option.depth_units, self._depth_units, True)
        presets = _option_range(0, len(rs.rs400_visual_preset.__members__) - 1, 1, 0)
        depth.add_option(rs.option.visual_preset, presets, True)

    def is_enabled(self) -> bool:
        return self._enabled

    def toggle_advanced_mode(self, enable: bool) -> None:
        if not enable:
            raise NotImplementedError("a software sensor can't drop the advanced-mode options")
        if not self._enabled:
            self._enabled = True
            self._camera.device.update_info(rs.camera_info.advanced_mode, "YES")
            self._add_options()

    def serialize_json(self) -> str:
        """The preset file, in the JSON librealsense writes"""
        if not self._enabled:
            raise RuntimeError("serialize_json() failed! Device is not in Advanced-Mode.")
        sensors = {sensor.name: sensor for sensor in self._camera.device.sensors}
        # librealsense keeps the depth units in the depth table, in micrometers
        depth_units = sensors[Sensor.STEREO_MODULE].get_option(rs.option.depth_units)
        self.groups["depth_table"]["depthUnits"] = round(depth_units * 1e6)

        parameters = {}
        for key, (group, field_name, scale) in _PRESET_KEYS.items():
            value = self.groups[group][field_name]
            if key == "param-usersm":
                value = 0 if value > 0 else 1
            parameters[key] = _preset_value(value / scale)
        for key, (sensor_name, control, names) in _PRESET_CONTROLS.items():
            sensor = sensors.get(sensor_name)
            option = rs.option.__members__[control]
            if sensor is None or option not in sensor.get_supported_options():
                continue
            value = sensor.get_option(option)
            parameters[key] = names[value] if names else _preset_value(value)

        device = self._camera.device
        info = {
            "name": rs.camera_info.name,
            "product line": rs.camera_info.product_line,
            "fw version": rs.camera_info.firmware_version,
        }
        preset = {
            "device": {k: device.get_info(i) for k, i in info.items() if device.supports(i)},
            "parameters": parameters,
            "schema version": 1,
        }
        return json.dumps(preset, indent=4, sort_keys=True)


def _preset_value(value: float) -> str:
    """VALUE as librealsense writes it in a preset file: a C++ stream's 6 significant digits"""
    return f"{value:g}"


def _option_range(
    minimum: float, maximum: float, step: float, default: float
) -> rs.option_range:
    rng = rs.option_range()
    rng.min, rng.max, rng.step, rng.default = minimum, maximum, step, default
    return rng


_BYTE_RAMP = bytes(range(256))


def pixels(size: int, frame_number: int) -> bytes:
    """
    The SIZE bytes of pixel data pushed in frame FRAME_NUMBER: a ramp of byte values that
    starts one higher in each frame
    """
    start = frame_number % 256
    ramp = _BYTE_RAMP * (size // 256 + 2)
    return ramp[start : start + size]


class Rect(NamedTuple):
    x: int
    y: int
    width: int
    height: int


# The depth pattern, in depth units (1 mm at the default `depth_units` of 0.001), laid out for
# the 640x480 depth profiles; a smaller image holds the part that fits
DEPTH_BACKGROUND = 2000
DEPTH_NEAR = 1000
DEPTH_FLICKER = 1500
NEAR_BLOCK = Rect(160, 120, 160, 120)
HOLE = Rect(400, 300, 80, 60)  # no depth
FLICKER_PATCH = Rect(560, 40, 16, 16)  # DEPTH_FLICKER in even frames, no depth in odd ones


def depth_pixels(width: int, height: int, frame_number: int) -> bytes:
    """
    The Z16 pixel data pushed in frame FRAME_NUMBER: DEPTH_BACKGROUND, with DEPTH_NEAR in
    NEAR_BLOCK, zeros in HOLE, and FLICKER_PATCH that has depth only in even frames
    """
    depth = array("H", [DEPTH_BACKGROUND]) * (width * height)
    flicker = DEPTH_FLICKER if frame_number % 2 == 0 else 0
    for rect, value in ((NEAR_BLOCK, DEPTH_NEAR), (HOLE, 0), (FLICKER_PATCH, flicker)):
        right = min(rect.x + rect.width, width)
        for y in range(rect.y, min(rect.y + rect.height, height)):
            depth[y * width + rect.x : y * width + right] = array("H", [value]) * (
                right - rect.x
            )
    return depth.tobytes()


def _add_stream(
    sensor: rs.software_sensor,
    profile: Profile,
    uid: int,
    is_default: bool,
    intrinsics: Intrinsics | None,
) -> rs.stream_profile:
    stream_type = getattr(rs.stream, profile.stream.split()[0].lower())
    index = max(profile.index, 0)
    fmt = getattr(rs.format, profile.format.lower())
    if stream_type in (rs.stream.gyro, rs.stream.accel):
        stream = rs.motion_stream()
    else:
        stream = rs.video_stream()
        stream.width = profile.resolution.width
        stream.height = profile.resolution.height
        stream.bpp = _BYTES_PER_PIXEL[profile.format.lower()]
        if intrinsics is not None:
            stream.intrinsics = _rs_intrinsics(profile.resolution, intrinsics)
    stream.type = stream_type
    stream.index = index
    stream.uid = uid
    stream.fps = profile.fps
    stream.fmt = fmt
    if isinstance(stream, rs.motion_stream):
        return sensor.add_motion_stream(stream, is_default)
    return sensor.add_video_stream(stream, is_default)


def _rs_intrinsics(resolution: Resolution, intrinsics: Intrinsics) -> rs.intrinsics:
    rs_intrinsics = rs.intrinsics()
    rs_intrinsics.width, rs_intrinsics.height = resolution
    rs_intrinsics.ppx, rs_intrinsics.ppy = intrinsics.ppx, intrinsics.ppy
    rs_intrinsics.fx, rs_intrinsics.fy = intrinsics.fx, intrinsics.fy
    rs_intrinsics.model = rs.distortion.__members__[intrinsics.model]
    rs_intrinsics.coeffs = list(intrinsics.coeffs)
    return rs_intrinsics


def _rs_extrinsics(
    rotation: tuple[float, ...], translation: tuple[float, ...]
) -> rs.extrinsics:
    rs_extrinsics = rs.extrinsics()
    rs_extrinsics.rotation = list(rotation)
    rs_extrinsics.translation = list(translation)
    return rs_extrinsics


def _video(stream: str, fps: int, fmt: str, index: int = -1) -> Profile:
    return Profile(stream, Resolution(640, 480), fps, fmt, index)


D435 = DeviceInfo(
    name="Intel RealSense D435",
    serial="012345678",
    fw="5.15.0.0",
    connection="3.2",
    sensors=[Sensor.STEREO_MODULE, Sensor.RGB_CAMERA, Sensor.MOTION_MODULE],
)

D435_CAMERA_INFO: dict[str, str] = {
    "recommended_firmware_version": "5.16.0.1",
    "physical_port": "/sys/devices/pci0000:00/usb2/2-1",
    "product_id": "0B07",
    "camera_locked": "YES",
    "connection_type": "USB",
    "product_line": "D400",
    "asic_serial_number": "123456789012",
    "imu_type": "BMI055",
}

_D435_DEPTH_INTRINSICS = Intrinsics(320.5, 240.25, 385.5, 385.12345, "brown_conrady", (0,) * 5)

D435_SENSORS: list[SensorSpec] = [
    SensorSpec(
        name=Sensor.STEREO_MODULE,
        profiles=[
            *(_video(Stream.DEPTH, fps, "z16", 0) for fps in (6, 15, 30)),
            *(_video(Stream.INFRARED, fps, "y8") for fps in (15, 30)),
            _video(Stream.INFRARED2, 30, "y8"),
        ],
        options=[
            Option("exposure", "", 1.0, 200000.0, 1.0, 8500.0, int),
            Option("enable_auto_exposure", "", 0.0, 1.0, 1.0, 1.0, int),
            Option("laser_power", "", 0.0, 360.0, 30.0, 150.0, int),
            Option("depth_units", "", 0.00001, 0.001, 0.00001, 0.001, float),
        ],
        read_only_options={"asic_temperature": 40.0},
        intrinsics=dict.fromkeys(
            (Stream.DEPTH, Stream.INFRARED, Stream.INFRARED2), _D435_DEPTH_INTRINSICS
        ),
    ),
    SensorSpec(
        name=Sensor.RGB_CAMERA,
        profiles=[
            *(_video(Stream.COLOR, fps, "rgb8", 0) for fps in (6, 15, 30)),
            _video(Stream.COLOR, 30, "yuyv"),
        ],
        options=[Option("brightness", "", -64.0, 64.0, 1.0, 0.0, int)],
        intrinsics={
            Stream.COLOR: Intrinsics(
                321.75,
                243.5,
                615.25,
                615.5,
                "inverse_brown_conrady",
                (0.125, -0.25, 0.001, -0.0005, 0.0625),
            )
        },
    ),
    SensorSpec(
        name=Sensor.MOTION_MODULE,
        profiles=[
            Profile(Stream.GYRO, Resolution(0, 0), 200, "motion_xyz32f", 0),
            Profile(Stream.ACCEL, Resolution(0, 0), 63, "motion_xyz32f", 0),
        ],
    ),
]


_IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)

D435_EXTRINSICS: list[Extrinsics] = [
    Extrinsics(Stream.DEPTH, Stream.INFRARED, _IDENTITY, (0, 0, 0)),
    Extrinsics(Stream.DEPTH, Stream.INFRARED2, _IDENTITY, (-0.05, 0, 0)),
    Extrinsics(Stream.DEPTH, Stream.COLOR, _IDENTITY, (0.0147, 0.0001, 0.0004)),
]


def d435(advanced_mode: bool = True) -> SoftwareCamera:
    return SoftwareCamera(
        D435, D435_SENSORS, D435_CAMERA_INFO, D435_EXTRINSICS, advanced_mode=advanced_mode
    )


def software_driver(*cameras: SoftwareCamera) -> Realsense:
    """The real driver over CAMERAS, with their advanced modes"""
    advanced_modes: dict[str, AdvancedMode] = {
        camera.info.serial: camera.advanced_mode
        for camera in cameras
        if camera.advanced_mode is not None
    }
    return Realsense([camera.device for camera in cameras], advanced_modes)


def d435_sensor(name: str) -> SensorSpec:
    return next(s for s in D435_SENSORS if s.name == name)
