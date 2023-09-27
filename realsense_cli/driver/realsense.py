import time
from collections import defaultdict
from typing import Optional

from loguru import logger

from realsense_cli.types import (
    DeviceInfo,
    Sensor,
    Option,
    Profile,
    Stream,
    Resolution,
    FrameSet,
    Frame,
    SafetyPreset,
    SafetyZone,
    SafetyMaskingZone,
)

import pyrealsense2 as rs  # type: ignore

from realsense_cli.utils import find_origin_sensor


class Realsense:
    """
    pyrealsense2 wrapper driver
    """

    def __init__(self):
        logger.info("Instancing Realsense driver")
        self._ctx: rs.context = rs.context()
        self._devices: list[rs.device] = []
        self._sensors: dict[rs.device, dict[Sensor, rs.sensor]] = {}
        self._streams_map: dict[Stream, rs.stream] = {
            Stream.DEPTH: rs.stream.depth,
            Stream.INFRARED: rs.stream.infrared,
            Stream.INFRARED2: rs.stream.infrared,
            Stream.COLOR: rs.stream.color,
            Stream.GYRO: rs.stream.gyro,
            Stream.ACCEL: rs.stream.accel,
            Stream.SAFETY: rs.stream.safety,
            Stream.LABELED_POINT_CLOUD: rs.stream.labeled_point_cloud,
            Stream.OCCUPANCY: rs.stream.occupancy,
        }
        self._metadata: list[rs.frame_metadata_value] = []
        self._stream_method: str = "pipe"

        self._setup()
        if self._devices:
            logger.debug(f"setting first device as active one")
            # sorting to be deterministic every run
            self._active_device = sorted(
                [(d.get_info(rs.camera_info.serial_number), d) for d in self._devices]
            )[0][1]
        else:
            self._active_device = None
        logger.info("active device: {}", self._active_device)
        self._streaming = False
        self._pipeline: rs.pipeline = rs.pipeline(self._ctx)
        self._pipe_profile: Optional[rs.pipeline_profile] = None
        self._frame_queue: rs.frame_queue = rs.frame_queue(capacity=1)

    def _setup(self) -> None:
        self._query()
        self._prep_valid_md_attrs()

    def _query(self):
        for dev in self._ctx.devices:
            logger.debug("Adding device: {}", dev)
            self._devices.append(dev)
            self._sensors[dev] = {}

            rs_sensor: rs.sensor
            for rs_sensor in dev.sensors:
                logger.debug("Adding sensor {} for device {}", rs_sensor, dev)
                self._sensors[dev][Sensor(rs_sensor.name)] = rs_sensor

        logger.info("Found {} devices", len(self._devices))

    def _prep_valid_md_attrs(self):
        for name in dir(rs.frame_metadata_value):
            attr = getattr(rs.frame_metadata_value, name)
            if isinstance(attr, rs.frame_metadata_value):
                self._metadata.append(attr)

    def query_devices(self) -> list[DeviceInfo]:
        """
        Query connected devices
        """
        devices = []
        rsdev: rs.device
        for device, sensors in self._sensors.items():
            rs_sensors = [s for s in sensors.values()]
            logger.debug("adding device info for device {}", device)

            def _safe_get_info(info: rs.camera_info):
                try:
                    return device.get_info(info)
                except Exception as e:
                    logger.error(e)
                return "N/A"

            info = DeviceInfo(
                name=device.get_info(rs.camera_info.name),
                serial=device.get_info(rs.camera_info.serial_number),
                fw=_safe_get_info(rs.camera_info.firmware_version),
                connection=_safe_get_info(rs.camera_info.usb_type_descriptor),
                sensors=[s.get_info(rs.camera_info.name) for s in rs_sensors],
            )
            logger.debug("adding device info: {}", info)
            devices.append(info)
        return devices

    def list_controls(self, sensor: Sensor) -> list[Option]:
        """
        List controls supported by SENSOR
        """
        rs_sensor = self._get_sensor(sensor)
        logger.info("listing controls for sensor {}", rs_sensor)

        options = rs_sensor.get_supported_options()
        res = []
        for option in options:
            logger.debug("querying option: {}", option)
            if rs_sensor.is_option_read_only(option):
                logger.debug("skipping read only option")
                continue
            rng: rs.option_range = rs_sensor.get_option_range(option)
            vtype = float
            if rng.step == int(rng.step) and rng.min == int(rng.min):
                vtype = int
            opt = Option(
                name=option.name,
                description=rs_sensor.get_option_description(option),
                min_value=round(rng.min, 6),
                max_value=round(rng.max, 6),
                step=round(rng.step, 6),
                default_value=round(rng.default, 6),
                vtype=vtype,
            )
            logger.debug("adding Option: {}", opt)
            res.append(opt)
        return res

    def get_control_values(self, sensor: Sensor, controls: list[str]) -> dict[str, float]:
        """
        Get values for CONTROLS from SENSOR
        """
        res = {}
        rs_sensor: rs.sensor = self._get_sensor(sensor)
        logger.info("querying controls {} for sensor {}", controls, rs_sensor)
        for control in controls:
            option = getattr(rs.option, control, None)
            logger.debug('getting value for option: "{}"', option)
            if not option or not rs_sensor.supports(option):
                raise ValueError(f"control '{control}' is not supported for sensor '{sensor}'")
            res[control] = rs_sensor.get_option(option)
            logger.debug('"{}" value: {}', option, res[control])
        return res

    def set_control_values(self, sensor: Sensor, control_values: dict[str, float]) -> None:
        """
        Set CONTROL_VALUES on SENSOR
        """
        rs_sensor = self._get_sensor(sensor)

        logger.info("setting controls {} for sensor {}", control_values, rs_sensor)
        for control, value in control_values.items():
            option = getattr(rs.option, control, None)
            logger.debug('setting "{}" with value {}', option, value)
            if not option or not rs_sensor.supports(option):
                logger.debug("no such option or not supported by sensor")
                raise ValueError(
                    f"control '{control}' is not supported for sensor '{sensor.value}'"
                )
            rs_sensor.set_option(option, value)

    def list_streams(self, sensor: Sensor) -> list[Profile]:
        """
        List supported streams for SENSOR
        """
        rs_sensor = self._get_sensor(sensor)
        logger.info("listing streams for sensor {}", rs_sensor)
        profiles: list[rs.stream_profile] = rs_sensor.get_stream_profiles()
        res = []
        for profile in profiles:
            logger.debug("found profile: {}", profile)
            if profile.is_video_stream_profile():
                vsp: rs.video_stream_profile = profile.as_video_stream_profile()
                width, height = vsp.width(), vsp.height()
            else:
                width, height = 0, 0

            res.append(
                Profile(
                    stream=Stream(profile.stream_name()),
                    resolution=Resolution(width, height),
                    fps=profile.fps(),
                    format=profile.format().name.upper(),
                    index=profile.stream_index(),
                )
            )
            logger.debug("adding profile {}", res[-1])
        return res

    def play(self, profiles: Optional[list[Profile]] = None, pipeline: bool = True) -> None:
        """
        Start streaming selected profiles
        """
        logger.info("Playing profiles: {}", profiles)
        if pipeline:
            self._stream_pipe(profiles)
        else:
            self._stream_sensor(profiles)
        self._streaming = True

    def _stream_sensor(self, profiles: list[Profile]):
        self._stream_method = "sensor"
        sensor_profiles = {}
        for sensor in self._sensors[self._active_device]:
            sensor_profiles[sensor] = self.list_streams(sensor)
        origin_streams: dict[Stream, Sensor] = find_origin_sensor(sensor_profiles)

        stream_profiles: dict[Sensor, list[Profile]] = {s: [] for s in origin_streams.values()}
        for profile in profiles:
            stream_profiles[origin_streams[profile.stream]].append(profile)

        rs_stream_profiles: dict[Sensor, list[rs.stream_profile]] = defaultdict(list)
        for sensor, sprofiles in stream_profiles.items():
            rs_sensor: rs.sensor = self._get_sensor(sensor)
            rs_profiles = rs_sensor.get_stream_profiles()

            for profile in sprofiles:
                logger.debug(f"Looking a match for {profile}")

                skip_index = profile.index == -1
                skip_fps = profile.fps == 0
                skip_width = profile.resolution.width == 0
                skip_height = profile.resolution.height == 0
                skip_format = profile.format == "any"
                fmt = getattr(rs.format, profile.format.lower())

                logger.debug(
                    f"{skip_index=}, {skip_fps=}, {skip_format=}, {skip_height=}, {skip_width=}"
                )

                for rs_profile in rs_profiles:
                    if rs_profile.is_video_stream_profile():
                        sp: rs.video_stream_profile = rs_profile.as_video_stream_profile()
                        width, height = sp.width(), sp.height()
                    else:
                        sp = rs_profile
                        width, height = 0, 0

                    logger.debug(f"checking {rs_profile}...")
                    if (
                        sp.stream_type() == self._streams_map[profile.stream]
                        and (skip_index or (sp.stream_index() == profile.index))
                        and (skip_format or (sp.format() == fmt))
                        and (skip_fps or (sp.fps() == profile.fps))
                        and (skip_width or (width == profile.resolution.width))
                        and (skip_height or (height == profile.resolution.height))
                    ):
                        logger.debug(f"Found match: {sp}")
                        rs_stream_profiles[sensor].append(sp)
                        break
                else:
                    raise RuntimeError(
                        f"Failed to find streaming profile: '{profile}' for {sensor}"
                    )

        for sensor, rs_profiles in rs_stream_profiles.items():
            logger.info(f"Starting stream for {sensor} with {rs_profiles}")
            rs_sensor = self._get_sensor(sensor)
            rs_sensor.open(rs_profiles)
            rs_sensor.start(self._frame_queue)

    def _stream_pipe(self, profiles):
        self._stream_method = "pipe"
        cfg = rs.config()
        cfg.enable_device(self._active_device.get_info(rs.camera_info.serial_number))
        if profiles:
            for profile in profiles:
                rs_stream = self._streams_map[profile.stream]
                rs_format = getattr(rs.format, profile.format.lower())
                cfg.enable_stream(
                    rs_stream,
                    profile.index,
                    profile.resolution.width,
                    profile.resolution.height,
                    rs_format,
                    profile.fps,
                )
        else:
            cfg.enable_all_streams()
        logger.info("Starting stream")
        self._pipe_profile = self._pipeline.start(cfg, self._frame_queue)

    def stop(self) -> None:
        """
        Stop streaming
        """
        logger.info("Stopping stream")
        if self._stream_method == "pipe":
            self._pipeline.stop()
        else:
            for rs_sensor in self._sensors[self._active_device].values():
                if rs_sensor.get_active_streams():
                    rs_sensor.stop()
                    rs_sensor.close()
        self._streaming = False

    def wait_for_frameset(self, timeout: float = 3.0) -> Optional[FrameSet]:
        """
        Get next frameset waiting in queue.
        return None when no frameset arrive after timeout
        """
        result: FrameSet = {}
        rs_frame: rs.frame = self._frame_queue.wait_for_frame(int(timeout * 1000))
        frames: list[rs.frame]
        if rs_frame.is_frameset():
            frames = [f for f in rs_frame.as_frameset()]
        else:
            frames = [rs_frame]
        logger.debug("frameset received")

        t0 = time.time()
        rs_frame: rs.frame
        for rs_frame in frames:
            t1 = time.time()
            rs_profile: rs.stream_profile = rs_frame.get_profile()
            profile = Profile.from_rs(rs_profile)
            metadata = {}
            for md in self._metadata:
                if rs_frame.supports_frame_metadata(md):
                    metadata[md.name] = rs_frame.get_frame_metadata(md)
            frame = Frame(
                profile=profile,
                timestamp=rs_frame.get_timestamp(),
                index=rs_frame.get_frame_number(),
                metadata=metadata,
            )
            logger.debug(
                "{}\t#{} {:.2}ms - {}",
                frame.profile.stream.value,
                frame.index,
                (time.time() - t1) * 1000,
                frame,
            )
            result[profile.stream] = frame
        logger.debug(f"Total callback time: {(time.time() - t0) * 1000:.2}ms")

        return result

    def reset(self):
        """
        Send hardware reset to device
        """
        self._active_device.hardware_reset()

    def _get_sensor(self, sensor: Sensor) -> rs.sensor:
        if sensor not in self._sensors[self._active_device]:
            raise RuntimeError(
                f'Sensor "{sensor.value}" is not supported on device: {self._active_device.get_info(rs.camera_info.serial_number)}'
            )
        return self._sensors[self._active_device][sensor]

    @property
    def sensors(self) -> list[Sensor]:
        return list(self._sensors[self._active_device].keys())

    @property
    def active_device(self) -> str:
        return self._active_device.get_info(rs.camera_info.serial_number)

    @active_device.setter
    def active_device(self, serial: Optional[str] = None):
        if not serial:
            return
        for dev in self._devices:
            if dev.get_info(rs.camera_info.serial_number) == serial:
                self._active_device = dev
                break
        else:
            raise ValueError(f"No device with serial {serial} is connected")

    def set_safety_preset(self, index: int, preset: SafetyPreset):
        safety: rs.safety_sensor = self._get_sensor(Sensor.SAFETY_CAMERA).as_safety_sensor()

        env = rs.safety_environment()
        env.grid_cell_size = preset.grid_cell_size
        env.surface_height = preset.surface_height
        env.surface_inclination = preset.surface_inclination
        env.safety_trigger_duration = preset.safety_trigger_duration
        env.surface_confidence = 1

        platform = rs.safety_platform()
        platform.robot_height = preset.robot_height
        rx = rs.float3(*preset.rotation[0])
        ry = rs.float3(*preset.rotation[1])
        rz = rs.float3(*preset.rotation[2])
        rotation = rs.float3x3(rx, ry, rz)
        translation = rs.float3(*preset.translation)
        platform.transformation_link = rs.safety_extrinsics_table(rotation, translation)

        zones = []
        for zone in preset.safety_zones:
            rs_zone = rs.safety_zone()
            rs_zone.minimum_object_size = rs.float2(50, 600)
            rs_zone.zone_polygon = [rs.float2(*point) for point in zone.points]
            zones.append(rs_zone)


        masks = []
        for mask in preset.masking_zones:
            rs_mask = rs.masking_zone()
            rs_mask.attributes = mask.attributes
            rs_mask.minimal_range = mask.minimal_range
            pixels = []
            for pixel in mask.pixels:
                pix = rs.pixel2D()
                pix.i, pix.j = pixel
                pixels.append(pix)
            rs_mask.region_of_interests = pixels
            masks.append(rs_mask)

        rs_preset = rs.safety_preset()
        rs_preset.environment = env
        rs_preset.platform_config = platform
        rs_preset.safety_zones = zones
        rs_preset.masking_zones = masks
        # TODO not working
        # safety.set_safety_preset(index, rs_preset)

    def get_safety_preset(self, index: int) -> SafetyPreset:
        safety: rs.safety_sensor = self._get_sensor(Sensor.SAFETY_CAMERA).as_safety_sensor()
        preset: rs.safety_preset = safety.get_safety_preset(index)

        # TODO move to dataclass as static method
        env: rs.safety_environment = preset.environment
        platform: rs.safety_platform = preset.platform_config
        zones: list[rs.safety_zone] = preset.safety_zones
        masks: list[rs.masking_zone] = preset.masking_zones

        def round2(num):
            return round(num, 2)

        raw_matrix = platform.transformation_link
        rx = raw_matrix.rotation.x
        ry = raw_matrix.rotation.y
        rz = raw_matrix.rotation.z
        translation = [round2(p) for p in [raw_matrix.translation.x,
                                           raw_matrix.translation.y,
                                           raw_matrix.translation.z]]
        rotation = [
            [rx.x, ry.x, rz.x],
            [rx.y, ry.y, rz.y],
            [rx.z, ry.z, rz.z],
        ]
        rotation = [[round2(element) for element in row] for row in rotation]

        new_zones = []
        for zone in zones:
            points = []
            for polygon in zone.zone_polygon:
                points.append((round2(polygon.x), round2(polygon.y)))
            new_zones.append(SafetyZone(
                points=points,
                trigger_confidence=zone.safety_trigger_confidence,
            ))

        nmasks = []
        for mask in masks:
            pixels = []
            for pixel in mask.region_of_interests:
                pixels.append((pixel.i, pixel.j))
            nmasks.append(SafetyMaskingZone(
                attributes=mask.attributes,
                pixels=pixels,
                minimal_range=mask.minimal_range
            ))

        return SafetyPreset(
            new_zones,
            nmasks,
            rotation,
            translation,
            round2(platform.robot_height),
            round2(env.grid_cell_size),
            round2(env.surface_height),
            round2(env.surface_inclination),
            round2(env.safety_trigger_duration),
            str(preset))

