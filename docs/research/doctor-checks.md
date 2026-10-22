# Which `rs doctor` checks pyrealsense2 and the OS can answer

Research for [#38](https://github.com/yegarti/realsense-cli/issues/38), feeding the grilling
ticket [#43 rs doctor: checks and report](https://github.com/yegarti/realsense-cli/issues/43).

**Question.** For a planned `rs doctor`, which environment problems can actually be detected,
and how? Covers udev rules, USB2 vs USB3 link, firmware vs `recommended_firmware_version`,
pyrealsense2 importable and its version, WSL with usbipd, permission errors and no device
found. For each: how it is detected, on which OS, whether it needs a connected device, and
whether the mock driver can exercise it.

**Sources.** librealsense at tag `v2.59.1`, the release pyrealsense2 2.59.1 is built from
(links below go to `realsenseai/librealsense`, where `IntelRealSense/librealsense` redirects).
Also Microsoft's WSL docs, the WSL kernel config, and usbipd-win. Where the table says
*verified*, I ran a throwaway script on this machine, kept outside the repo: WSL2, kernel
`6.18.54.1-microsoft-standard-WSL2`, Ubuntu with systemd, pyrealsense2 2.59.1.11053 from PyPI,
usbipd-win 5.3.0. **A D435i (FW 5.17.3.10) was attached through usbipd.** No native Linux,
native Windows or USB2 port was available, so those paths are backed by source only.

## Answer

Every item on the list can be detected, but two need a different approach than the ticket
assumes:

- **`recommended_firmware_version` is gone.** librealsense 2.58.1 stopped bundling D400
  firmware, and since then no real device registers the field. A firmware check has to get the
  recommended version elsewhere: the Viewer's online versions DB, or a table baked into `rs`.
- **Permission errors look exactly like "no device found".** The V4L2 backend catches the
  failed `open()` and logs it at INFO, and the camera just disappears from `query_devices()`.
  To tell the two apart, `rs doctor` has to look below the SDK: capture the SDK log, scan
  sysfs, and on WSL ask `usbipd.exe`.

Checks that read `camera_info` or sensors through the driver can be tested on the mock
(`SoftwareCamera` accepts any `camera_info`). Checks that read the OS (sysfs, udev files,
`/proc`, `usbipd.exe`, the registry, the import) can't run on `RSCLI_DRIVER=mock`. They need
seams (a filesystem root, a command runner, an importer) and unit tests against fakes.

| Check | How it's detected | OS | Needs device | Mock-testable |
|---|---|---|---|---|
| pyrealsense2 installed, version | `importlib.metadata.version("pyrealsense2")` (no import), then `import pyrealsense2` inside try/except; `rs.__version__`, `rs.__full_version__` | all | no | no (the mock itself needs pyrealsense2); unit test with a fake importer |
| pyrealsense2 loads | the import fails with `ImportError` if `libusb-1.0.so.0` / `libudev.so.1` are missing: the Linux wheel links them from the system and does not vendor them | Linux | no | unit test only |
| SDK up to date (optional) | compare with the `LIBREALSENSE` entry in the Viewer's versions DB (network) | all | no | yes, with an injected DB |
| Device found by the SDK | `rs.context().query_devices()` (already `require_device`) | all | yes | yes (zero or more software devices) |
| Camera on the USB bus | scan `/sys/bus/usb/devices/*/idVendor` for `8086` / `38e5`, and the interfaces' bound driver (`uvcvideo`) | Linux, WSL | yes | unit test with a fake sysfs root |
| Camera on the Windows host but not attached to WSL | `usbipd.exe state` (JSON) or `usbipd.exe list` run from WSL through interop; no admin needed. Device attached through USB/IP: `physical_port` contains `vhci_hcd` | WSL | yes (on the host) | unit test with a fake command runner |
| Running under WSL | `/proc/sys/kernel/osrelease` contains `microsoft`; `WSL_DISTRO_NAME` is set | Linux | no | unit test |
| Permission denied on device nodes | `os.access(R_OK\|W_OK)` on the `/dev/videoN` of RealSense USB devices; and/or capture the SDK log while enumerating and look for `Cannot open ... Last Error: Permission denied` | Linux, WSL | yes | log parsing yes (`rs.log()` feeds the callback, verified); node access with a fake root |
| udev rules installed | the Viewer's recipe: `/etc/udev/rules.d/99-realsense-libusb.rules` (source install) or `/lib/udev/rules.d/60-librealsense2-udev-rules.rules` (deb); missing, or both present ("Multiple realsense udev-rules were found!"); `##Version=x.y##` header | Linux, WSL | no | unit test with a fake root |
| USB2 link | `usb_type_descriptor` starts with `2.` (what the Viewer, DQT and on-chip-calib check). On Linux, sysfs `speed` (`480` vs `5000`+) is the raw link speed | all (sysfs: Linux) | yes | yes (`connection="2.1"` on a software device) |
| Firmware up to date | `firmware_version` vs the versions DB `FIRMWARE`/`RECOMMENDED` entry for the device name, minus the "Intel " prefix; `recommended_firmware_version` is never present on 2.58+ | all | yes | yes (name and fw are registerable; inject the DB) |
| Partial device (e.g. IMU missing) | `imu_type` registered but no `Motion Module` sensor, and/or SDK warning `HID Motion Sensor Failure (continuing as partial device)` | all (cause: Linux kernel) | yes | yes (software D435i without a motion sensor) |
| IMU kernel support | `/sys/bus/iio/devices` missing / `CONFIG_HID_SENSOR_HUB` not set (`/proc/config.gz`) | Linux, WSL | no | unit test |
| Frame metadata available | stream a few frames, then `frame.supports_frame_metadata(frame_timestamp)` | all | yes, and streaming | depends on the mock pushing metadata (unchecked) |
| Windows metadata registry keys | `MetadataBufferSizeInKB0` under `HKLM\SYSTEM\CurrentControlSet\Control\DeviceClasses\{e5323777-…}\<instance>\#GLOBAL\Device Parameters` | Windows | yes | unit test (fake registry) |
| Windows camera privacy | not readable from the SDK; a hint when no device is found | Windows | n/a | n/a |

## Findings, check by check

### pyrealsense2 installed, importable, and its version

- `rs` declares `pyrealsense2>=2.56.5` as a hard dependency (`pyproject.toml`), and imports it
  only inside `create_driver()`. So `rs doctor` can run, and report, even when the import
  fails.
- PyPI 2.59.1.11053 ships wheels only for manylinux x86_64 (cp310 to cp314), manylinux aarch64
  (cp39, cp310, cp312 only) and win_amd64. There is no macOS wheel and no sdist
  ([PyPI JSON](https://pypi.org/pypi/pyrealsense2/2.59.1.11053/json)). On those platforms the
  install of `rs` fails, so `rs doctor` never runs there. Doctor can't help with this case.
- The Linux wheel's extension has `NEEDED libusb-1.0.so.0` and `libudev.so.1`, and the wheel
  ships no vendored `.libs` directory (verified with `readelf -d`). On a minimal system without
  these, the import raises `ImportError` naming the missing library. Inferred from the NEEDED
  entries; not reproduced, since this machine has both.
- The wheel does **not** link `librealsense2.so`: the SDK is built into the extension. A
  system librealsense deb doesn't conflict with it (this machine has deb 2.57.7 and wheel
  2.59.1 side by side). The deb matters only for its udev rules package.
- Version: `importlib.metadata.version("pyrealsense2")` gives `2.59.1.11053` without loading
  the extension. After import, `rs.__version__` is `2.59.1` and `rs.__full_version__` is
  `2.59.1.11053` (verified).

### Which backend the wheel uses, and why it matters

The Linux x86_64 wheel is built with the **V4L2 backend**, not RSUSB/libusb. Its extension
contains `platform::v4l_backend`, `v4l_hid_device` and `iio_hid_sensor`, and no
`rs_uvc_device` (verified with `strings`). `physical_port` is a `.../video4linux/video0` sysfs
path (verified). The backend choice is the `FORCE_RSUSB_BACKEND` switch in
[`CMake/unix_config.cmake` L109-115](https://github.com/realsenseai/librealsense/blob/v2.59.1/CMake/unix_config.cmake#L109-L115).

So on Linux, streaming goes through the kernel's `uvcvideo` and `/dev/video*`, and the IMU
goes through the kernel's HID-sensor/IIO drivers. Permissions on those nodes, and kernel
support for them, are what doctor has to check. Raw `/dev/bus/usb` access matters less (the
backend still links libusb, for other paths such as firmware update).

### Device found, and why it isn't

`query_devices()` returning nothing has several causes, and each layer below the SDK can be
asked separately:

1. **Not on the bus at all.** On Linux, `/sys/bus/usb/devices/*/idVendor` lists every USB
   device. RealSense vendor IDs are `0x8086` (D4xx) and `0x38E5` (D5xx, `VID_REALSENSE_CAMERA`,
   [`src/usb/usb-types.h` L42](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/usb/usb-types.h#L42)).
   The udev rules list the product IDs. Here, `2-1` is `8086:0b3a`, and its interfaces 0-4 are
   bound to `uvcvideo` and interface 5 (the HID IMU) to `usbhid` (verified).
2. **WSL: on the Windows host but not attached.** `usbipd.exe` (installed under
   `C:\Program Files\usbipd-win\`) is on the WSL `PATH` through interop. `usbipd.exe list` and
   `usbipd.exe state` (JSON with `BusId`, `InstanceId` with `VID_8086&PID_0B3A`,
   `ClientIPAddress`) run from inside WSL without admin (verified). They show each RealSense
   device as `Not shared` / `Shared` / `Attached`. Microsoft's guide: `usbipd bind` needs
   admin; `usbipd attach --wsl --busid <id>` doesn't
   ([Connect USB devices](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)).
3. **On the bus but the SDK can't open it.** That's the permissions case below.
4. **Windows native.** librealsense's troubleshooting table: "The camera is not recognized by
   the SDK", caused by "The SDK does not have access to the camera". Fix: turn on "Allow desktop
   apps to access your camera" in Settings, Privacy, Camera
   ([`doc/installation_windows.md` L97](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/installation_windows.md?plain=1#L97)).
   I found no API for reading that setting; it can only be a hint.

### Permission errors

- While enumerating, the V4L2 backend opens each `/dev/videoN` to query its capabilities.
  `get_dev_capabilities` throws ``"<fn>: Cannot open '<dev>"`` when `open()` fails
  ([`src/linux/backend-v4l2.cpp` L311-319](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/linux/backend-v4l2.cpp#L311-L319)),
  and `linux_backend_exception` appends `" Last Error: " + strerror(errno)`
  ([`src/librealsense-exception.h` L88-100](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/librealsense-exception.h#L88-L100)).
- `collect_uvc_nodes` catches it and logs at **INFO**: `Not a USB video device: ...`
  ([L1238-1241](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/linux/backend-v4l2.cpp#L1238-L1241)).
  The node is skipped, and the camera is missing from `query_devices()`. No exception reaches
  Python.
- Opening the device later retries for up to 5 s on `EACCES` while `/run/udev/queue` exists,
  i.e. while udev is still applying rules
  ([L2431-2445](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/linux/backend-v4l2.cpp#L2431-L2445)).
- **Detection.** Either check access directly (`os.access` on the `/dev/videoN` whose sysfs
  path sits under a RealSense USB device), or capture the SDK log during `query_devices()` and
  look for `Cannot open` / `Permission denied`. The log capture was verified to work:
  `rs.log_to_callback(rs.log_severity.info, cb)` receives the enumeration messages, `rs.log()`
  injects a fake one, and `rs.reset_logger()` detaches the callback.
- **Gotcha:** an exception raised inside the log callback **aborts the process**
  (`terminate called after throwing an instance of 'pybind11::error_already_set'`, verified).
  The callback must catch everything.
- **Not reproduced.** On this machine the nodes are `crw-rw-rw- root plugdev`. Denying access
  needs root, and a user+mount-namespace bind mount was refused ("must be superuser to use
  mount"). The exact log line above comes from source only.

### udev rules

- What librealsense ships: [`config/99-realsense-libusb.rules`](https://github.com/realsenseai/librealsense/blob/v2.59.1/config/99-realsense-libusb.rules),
  installed to `/etc/udev/rules.d/` by `scripts/setup_udev_rules.sh`. The
  `librealsense2-udev-rules` deb installs `/lib/udev/rules.d/60-librealsense2-udev-rules.rules`
  instead ([`doc/distribution_linux.md`](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/distribution_linux.md)).
  The rules set `MODE:="0666", GROUP:="plugdev"` on each RealSense VID:PID, and chmod the
  IIO/HID sysfs nodes for IMU devices.
- The Viewer's own check, `viewer_model::check_permissions`
  ([`common/viewer.cpp` L760-850](https://github.com/realsenseai/librealsense/blob/v2.59.1/common/viewer.cpp#L760-L850)),
  is a ready-made recipe:
  - it looks only at those two exact paths;
  - neither present: "RealSense UDEV-Rules are missing!";
  - both present: "Multiple realsense udev-rules were found!" (also listed in
    [`doc/installation.md` L150](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/installation.md?plain=1#L150));
  - otherwise it compares the file's `##Version=x.y##` header with the rules built into the
    Viewer.
- The version header is a weak signal. This machine's deb rules (2.57.7) and the 2.59.1 source
  rules both say `##Version=1.1##`, yet the deb file lacks the `38e5` (D5xx) vendor lines
  (verified by `diff`). `rs` doesn't ship the rules text either (the wheel doesn't embed it).
  A content check is more useful: does a rule line mention the attached device's `idProduct`?
  The node-access check above tests the actual effect.
- WSL: udev runs only if the distro runs it (here `systemd=true` in `/etc/wsl.conf` and
  `systemd-udevd` is running). usbipd-win's wiki: "Rules to enable a device must be in place
  before attaching the device"
  ([WSL support](https://github.com/dorssel/usbipd-win/wiki/WSL-support)). Not checked: what
  node permissions look like under WSL without systemd.

### USB2 vs USB3 link (`usb_type_descriptor`)

- D400 registers `connection_type` (`USB` or `GMSL`) and, on USB, `usb_type_descriptor`
  ([`src/ds/d400/d400-device.cpp` L1129-1133](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/ds/d400/d400-device.cpp#L1129-L1133)),
  for FW ≥ 5.9.8.0 ([L725-737](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/ds/d400/d400-device.cpp#L725-L737)).
- The value is the device descriptor's `bcdUSB`, mapped to `1.0`…`3.2`
  ([`src/usb/usb-types.h` L125-145](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/usb/usb-types.h#L125-L145)).
  On V4L2 it comes from sysfs `<usb device>/version`
  ([`src/linux/v4l-usb-logic.cpp` L139-165](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/linux/v4l-usb-logic.cpp#L139-L165)).
  Here sysfs `version` is ` 3.20` and `usb_type_descriptor` is `3.2` (verified).
- How librealsense's own tools decide "USB2": `usb_type.find("2.")` in
  [`tools/depth-quality/depth-quality-model.cpp` L60-66](https://github.com/realsenseai/librealsense/blob/v2.59.1/tools/depth-quality/depth-quality-model.cpp#L60-L66),
  and `!starts_with(desc, "3.")` in
  [`common/on-chip-calib.cpp` L289-293](https://github.com/realsenseai/librealsense/blob/v2.59.1/common/on-chip-calib.cpp#L289-L293).
  Both then lower the FPS.
- On Linux, sysfs `speed` gives the negotiated link directly: `480` is high-speed (USB2),
  `5000` and up is SuperSpeed. Here it's `5000`, through the usbipd `vhci_hcd` SuperSpeed root
  hub (verified). **Not verified on a real USB2 port.**
- Already exposed by `rs`: the driver reads `usb_type_descriptor` into `DeviceInfo.connection`.
  On the mock, `D435.connection = "3.2"`, and a software device registers any value.

### Firmware vs recommended firmware

- **`recommended_firmware_version` isn't reported on 2.59.1.** In v2.57.4, D400 registered it
  from the bundled `D4XX_RECOMMENDED_FIRMWARE_VERSION`
  ([v2.57.4 `d400-device.cpp` L972](https://github.com/realsenseai/librealsense/blob/v2.57.4/src/ds/d400/d400-device.cpp#L972)).
  In v2.58.4 and v2.59.1, nothing in `src/` (D400 or D500) registers it, except the ROS2 bag
  reader's `"0.0.0.0"` placeholder. The v2.58.1 release notes say: "Bundled D400 firmware removed from the SDK
  package" ([v2.58.1](https://github.com/realsenseai/librealsense/releases/tag/v2.58.1)).
  The attached D435i reports every other field but not this one (verified).
- What the Viewer uses instead: the online versions DB
  `https://librealsense.realsenseai.com/Releases/rs_versions_db.json`
  ([`common/device-model.h` L69](https://github.com/realsenseai/librealsense/blob/v2.59.1/common/device-model.h#L69)).
  It lists `{device_name, policy_type, component, version, platform, link}` entries, with
  `component` `FIRMWARE` or `LIBREALSENSE`. Today: `5.17.3.10` for D435/D435I/D435IF/D455/D455F/
  D456/D457, `5.17.0.10` for `Intel RealSense D4*`, and LIBREALSENSE `2.59.1` (fetched
  2026-10-22). Names are matched with the "Intel " prefix stripped and `*` as a wildcard
  ([`common/sw-update/versions-db-manager.cpp` L300-330](https://github.com/realsenseai/librealsense/blob/v2.59.1/common/sw-update/versions-db-manager.cpp#L300-L330)).
  This is needed because the camera here calls itself `RealSense D435I`.
- The alternative is a static table copied from the release notes' minimum-firmware table:
  "D435, D435if, D435i, D455, D455F, D456 USB: 5.17.3.10 or later", "Other D400 USB: 5.17.0.10
  or later" ([v2.59.1 notes](https://github.com/realsenseai/librealsense/releases/tag/v2.59.1)).
  It needs updating with each SDK bump.
- Mock: `firmware_version` and the name are registerable, so the comparison is testable with
  an injected DB or table. Note that `D435_CAMERA_INFO` in `driver/software.py` still
  registers `recommended_firmware_version: 5.16.0.1`, which no real camera on pyrealsense2
  2.58+ reports.

### WSL and usbipd

- WSL detection: the kernel release ends in `microsoft-standard-WSL2`, and `WSL_DISTRO_NAME`
  / `WSL_INTEROP` are set (verified).
- A device attached through USB/IP sits under `vhci_hcd`: here `physical_port` is
  `/sys/devices/platform/vhci_hcd.0/usb2/2-1/...` (verified). That links a camera to usbipd
  with no extra tools.
- Kernel prerequisites: Microsoft requires WSL kernel 5.10.60.1 or later for usbipd
  ([Connect USB devices](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)). The
  stock WSL kernel config has `CONFIG_USB_VIDEO_CLASS=m` and `CONFIG_USBIP_VHCI_HCD`, but
  `# CONFIG_HID_SENSOR_HUB is not set`, on both the 6.18 and 5.15 branches
  ([config-wsl 6.18](https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.y/arch/x86/configs/config-wsl)).
  So **depth and colour work on stock WSL, the IMU doesn't.** The D435i here enumerates as a
  partial device with only `Stereo Module` and `RGB Camera`, and the SDK warns
  `No HID info provided, IMU is disabled` and
  `RealSense D435I #918512073869 - HID Motion Sensor Failure (continuing as partial device): bad optional access`
  (verified; source [`ds-motion-common.cpp` L452](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/ds/ds-motion-common.cpp#L452),
  [`d400-motion.cpp` L209-212](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/ds/d400/d400-motion.cpp#L209-L212)).
  Partial devices became the default in v2.58.1 ("Partial-device-allowed is now the default").
- Frame metadata does work on stock WSL 6.18: depth frames report 22 metadata fields, colour 19
  (verified). That matches [`doc/installation.md` L90-91](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/installation.md?plain=1#L90-L91):
  mainline `uvcvideo` already carries metadata for most models.
- Attachments don't survive a reset. usbipd-win's README: "You will have to re-attach after a
  reboot, or when the device resets or is physically unplugged/replugged", unless attached
  with `usbipd attach --auto-attach` ("Automatically re-attach when the device is detached or
  unplugged", `usbipd attach --help`, verified on 5.3.0). **Not tested**: what `rs reset` does
  on WSL without `--auto-attach`. I didn't reset, so as not to detach the user's camera.
- librealsense doesn't support VMs: "the *librealsense* team does not support installation in
  a VM" ([`doc/installation.md` L14-15](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/installation.md?plain=1#L14-L15)).
  WSL2 is a VM, so a doctor report can fairly say so.

### Frame metadata (beyond the list, cheap to add)

- Linux needs a `uvcvideo` that knows the model. Windows needs per-device registry keys
  `MetadataBufferSizeInKB0` (set by `scripts/realsense_metadata_win10.ps1`, "must be executed
  each time a new RealSense device is attached",
  [`doc/installation_windows.md` L34-68](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/installation_windows.md?plain=1#L34-L68)).
- An OS-neutral detection is to stream a few frames and check
  `supports_frame_metadata(frame_timestamp)`. Without metadata the timestamp reader falls back
  from `hardware_clock`
  ([`src/ds/ds-timestamp.cpp` L120-121](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/ds/ds-timestamp.cpp#L120-L121)).
- This is the only check that needs streaming. It's a bounded run, so it fits the existing
  `rs stream play --frames` machinery.

## Open questions surfaced

1. **Where firmware recency comes from**: the online versions DB (the first network call in
   `rs`, unavailable offline/in labs), a table baked into `rs` and bumped with pyrealsense2, or
   no firmware check at all. A decision for #43.
2. **The mock reports a field real cameras no longer have**: `D435_CAMERA_INFO` registers
   `recommended_firmware_version`, so tests can pass on behaviour a real 2.58+ camera never
   shows. A small chore ticket.
3. **`rs reset` on WSL**: the reset drops the usbipd attachment unless it was made with
   `--auto-attach`. Does `rs reset --wait` then wait for a reconnect that never comes? Needs a
   hardware check, possibly its own ticket.
4. **Partial devices in general**: a D435i on WSL (or on any kernel without HID sensor support)
   silently loses its Motion Module. Should `rs list` / `rs info` flag partial devices, or only
   `rs doctor`? Partly #43, partly beyond it.
5. **No-wheel platforms** (macOS, aarch64 cp311/313/314): `rs` can't even install, so doctor
   can't report it. Only relevant if pyrealsense2 ever becomes optional; probably out of scope.
