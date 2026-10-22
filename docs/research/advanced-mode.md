# Advanced mode in pyrealsense2 2.59.1

Research for [#34](https://github.com/yegarti/realsense-cli/issues/34), feeding
[#40 rs preset load and save](https://github.com/yegarti/realsense-cli/issues/40) and
[#41 Querying and editing advanced controls](https://github.com/yegarti/realsense-cli/issues/41).

Sources are librealsense at tag `v2.59.1` (the version in `uv.lock`; the repo now lives at
`realsenseai/librealsense`, and `IntelRealSense/librealsense` redirects there). `src:` below
abbreviates `https://github.com/IntelRealSense/librealsense/blob/v2.59.1/`. "Verified" means
run against the installed `pyrealsense2==2.59.1` wheel and the repo's simulated D435
(`realsense_cli/driver/software.py`). **No camera was connected**: everything marked
*hardware-only* comes from source reading and was not observed.

## Short answer

- **Python API**: `rs.rs400_advanced_mode(dev)` exposes `is_enabled`, `toggle_advanced_mode`, 13
  `get_<group>(mode=0)`/`set_<group>(struct)` pairs, `get_all_controls()`,
  `serialize_json()`/`load_json(str)`, and a mapping interface (`am.keys()`, `am[group]`,
  `am[group, mode]`, `am[group] = struct`). `rs.serializable_device(dev)` has only
  `serialize_json`/`load_json`.
- **Toggling** advanced mode sends a firmware command and then **hardware-resets the device**:
  it disconnects and re-enumerates, so every handle (the `rs.device` and the
  `rs400_advanced_mode` wrapper) goes stale. The *mode* survives the reset. The *control
  values* are never written to flash (inferred from source; *hardware-only*).
- **Product lines**: D400 (all USB models; not D457 or the GMSL/MIPI variants) and D500 (always
  enabled, so it can't be toggled). DDS (Ethernet) devices are `serializable` only, with a
  different JSON shape.
- **Preset JSON**: `{"schema version": 1, "device": {...}, "parameters": {key: "string value"}}`,
  or a legacy flat object. Keys are `param-*` / `aux-param-*` (advanced groups, some scaled) and
  `controls-*` (ordinary sensor options). An unknown key fails the whole load. Only the product
  line must match the camera.
- **Ranges**: `mode` 0/1/2 gives current/min/max as the same struct type, so ranges are
  per-field. `hdad` (and `ae_control` on some devices) has no min/max: the query fails, and
  `get_all_controls()` substitutes the current value.
- **Software device**: no advanced-mode or serializable extension. `rs400_advanced_mode(sw_dev)`
  and `serializable_device(sw_dev)` *construct fine*, and then every call except `keys()` raises
  `RuntimeError: null pointer passed for argument "dev"`. The group structs (`STDepthControlGroup`
  etc.) are plain constructible Python objects. The mock-testable path is therefore a
  Python fake of the advanced-mode object, served through a seam in the driver.

## 1. Enabling and disabling advanced mode

| Fact | Source |
|---|---|
| `toggle_advanced_mode(enable)` sends `EN_ADV`, then runs the device's `hardware_reset()` (or `HWRST`) | src:`src/ds/advanced_mode/advanced_mode.cpp#L105-L125` |
| The enabled state is read once, when the device object is built (`UAMG` → `_enabled`). `toggle_advanced_mode` doesn't update it, so `is_enabled()` on the old handle is stale | src:`src/ds/advanced_mode/advanced_mode.cpp#L88-L103` |
| Official example: "At this point the device will disconnect and re-connect. The 'dev' object will become invalid and we need to initialize it again" (it sleeps 5 s, then re-queries devices) | src:`wrappers/python/examples/python-rs400-advanced-mode-example.py#L31-L41` |
| Live test: a toggle must be followed by a reconnect (`devices_changed` callback matched by serial, up to **30 s**), and a fresh `rs400_advanced_mode(new_dev).is_enabled()` then reports the new state | src:`unit-tests/live/hw-reset/pytest-advanced-mode-toggle.py#L19`, `#L49-L104` |
| The mode persists across resets and sessions: it survives the reset that toggling causes (the test above), and CI cameras are expected to "already be enabled" | src:`unit-tests/live/options/pytest-advanced-mode.py#L23` |
| Toggling off unregisters `visual_preset` and the writable `depth_units` from the depth sensor; toggling on re-registers them | src:`src/ds/advanced_mode/advanced_mode.cpp#L105-L125` |
| D400 with advanced mode off: `depth_units` is a **read-only constant** (0.001, or 0.0001 on D405/D401), and `visual_preset` is absent. Writable `depth_units` needs advanced mode and FW ≥ 5.6.3.0 | src:`src/ds/d400/d400-device.cpp#L1073-L1099`, `src/ds/advanced_mode/advanced_mode.cpp#L17-L26`, `#L88-L96` |
| D400 registers `camera_info.advanced_mode` = `"YES"`/`"NO"` (so `rs info`, which prints every camera info field, already shows it on a real D400). D500 does not register it | src:`src/ds/d400/d400-device.cpp#L1121` |
| D500: "d500 devices always in advanced mode"; "advanced mode toggling is not enabled" for D500 | src:`src/ds/d500/d500-device.h#L153`, `src/ds/advanced_mode/advanced_mode.cpp#L71-L72` |
| Control values are sent with `SET_ADV` (then a 20 ms sleep). No command saves them to flash, and `load_json` re-reads the camera's current values first, so values set in one session are lost on power-cycle or hardware reset. This is **inferred** from the absence of a save path (*hardware-only*, unverified) | src:`src/core/advanced_mode.h#L248-L259` |
| Docs: "It is recommended to set advanced mode controls when not streaming" | src:`doc/rs400/rs400_advanced_mode.md#L358` |

Consequences for the CLI:
- An enable or disable is a disconnect and reconnect, like `rs reset`, so the existing
  reset-and-wait logic applies. Afterwards the session must re-acquire the device by serial.
- Toggling is **idempotence-sensitive**: `toggle_advanced_mode(True)` on an already-enabled camera
  still resets it, so check `is_enabled()` first.
- `visual_preset` and writable `depth_units` existing only in advanced mode affects
  `rs config`: on a D400 with advanced mode off, `rs config set depth_units` hits a read-only
  control.

## 2. Preset files (`serialize_json` / `load_json`)

### Which devices

- `rs400::advanced_mode` derives from `rs2::serializable_device` in C++, and the internal
  `ds_advanced_mode_interface` derives from `serializable_interface`. Every advanced-mode device is
  therefore serializable (src:`include/librealsense2/rs_advanced_mode.hpp#L14`,
  src:`src/core/advanced_mode.h#L56`).
- **D400**: every class in `d400-factory.cpp` mixes in `ds_advanced_mode_base`, except
  `rs401_gmsl_device`, `rs415_gmsl_device`, `rs457_device` (D457) and `rs430_gmsl_device`
  (src:`src/ds/d400/d400-factory.cpp#L81`, `#L286`, `#L737`, `#L775`). D435 is
  `rs435_device` (`#L696`).
- **D500**: `rs500_device`, `rs5x5_device`, `rs5x5_dedicated_color_device`,
  `rs585_legacy_device`, `rs585s_device` and `rs555_device` all mix in `ds_advanced_mode_base`
  (src:`src/ds/d500/d500-factory.cpp#L63-L66` and on). Upstream live tests run the
  advanced-mode and preset suites on `D400*` and `D500*` (src:`unit-tests/live/options/pytest-presets.py`).
- **DDS devices** implement only `serializable_interface` (`dds_serializable`). Their JSON keys
  are `"<sensor name>/<option name>"` for every writable option, with `visual_preset` applied
  first (src:`src/dds/rsdds-serializable.cpp#L28-L90`). They are not covered further here.
- In **Python**, `rs400_advanced_mode` and `serializable_device` are separate classes with no
  base class, and `rs.device` has no `is_`/`as_` method for either extension
  (src:`wrappers/python/pyrs_advanced_mode.cpp#L285`, `#L352-L357`, verified).
  Detection is: construct, call `is_enabled()` (or `serialize_json()`), and catch `RuntimeError`.
  The C++ constructor nulls the handle on an unsupported device instead of raising
  (src:`include/librealsense2/rs_advanced_mode.hpp#L17-L26`). So the upstream test's
  `try: rs400_advanced_mode(dev) except: skip` never fires (verified on the software device).

### Preconditions and behaviour

- Both calls **require advanced mode enabled**: `wrong_api_call_sequence_exception`, "serialize_json()
  failed! Device is not in Advanced-Mode." / "load_json(...) failed! ..."
  (src:`src/ds/advanced_mode/advanced_mode.cpp#L844-L865`).
- `load_json` = `get_all()` (read every current value) → overlay the JSON keys → `set_all()`
  → set `visual_preset` to `custom`. A **partial preset is fine**: absent keys keep the camera's
  current values (src:`src/ds/advanced_mode/advanced_mode.cpp#L854-L865`,
  src:`src/ds/advanced_mode/json_loader.hpp#L610-L700`).
- `set_all` writes the depth groups, then depth options (laser state, then power if on; auto
  exposure, then gain and exposure if manual), then color options when
  `should_set_rgb_preset()` (D400 only; the D500 preset test asserts color options are untouched),
  then the HDR preset (src:`src/ds/advanced_mode/advanced_mode.cpp#L916-L960`,
  src:`unit-tests/live/options/pytest-presets.py#L99`).
- The live round-trip test is: `saved = am.serialize_json()`, change a group, check
  `visual_preset == custom`, then `am.load_json(saved)` restores it
  (src:`unit-tests/live/options/pytest-presets.py#L45-L58`).

### JSON schema

Written by `json_preset_writer` (src:`src/serialized-utilities.cpp#L12`, `#L146-L188`):

```json
{
  "device": {"fw version": "5.16.0.1", "name": "Intel RealSense D435", "product line": "D400"},
  "parameters": {
    "param-robbinsmonroincrement": "10",
    "controls-laserpower": "150",
    "controls-autoexposure-auto": "True",
    "...": "..."
  },
  "schema version": 1
}
```

Values are written as **strings**. The reader also accepts numbers.

Reading (`json_preset_reader`, src:`src/serialized-utilities.cpp#L14-L135`):
- With `"schema version"` it must be `1` (otherwise "mismatch on schema version"), and
  `"parameters"` must be present. With neither key, the whole object is the parameter map (the
  **legacy flat format**, e.g. the wiki's `DefaultPreset_D435.json` and the Android assets). With
  only one of them: "preset file is corrupt, cannot validate schema".
- Device check: `update_structs` clears the file's `name` and `fw version` before checking
  ("Allow cross-device compatibility (e.g., loading a D415 json to a D435)"). Only
  `"product line"` is enforced, so a D400 preset is rejected on a D500 ("preset product line
  does not match the connected device") (src:`src/ds/advanced_mode/json_loader.hpp#L615-L621`).
- **An unknown key aborts the load**: "`<key>` key is not supported by the connected device!". A
  value that fails to parse: `Couldn't set "<key>"` (src:`json_loader.hpp#L626-L661`).
  Because `controls-*` keys are only registered when the camera supports that option (`was_set`
  in `get_all`), a preset carrying `controls-color-*` fails on a camera without a color sensor
  (src:`json_loader.hpp#L424-L449`).
- Validation is weak: numbers are parsed with `atof`, so `"abc"` loads as 0. An unrecognised
  string for a string control (`controls-laserstate`, `controls-*-auto`) loads as 0, because
  `std::map::operator[]` inserts a default. Neither raises, and the struct types don't range-check
  (src:`json_loader.hpp#L133-L180`). A CLI that wants clear errors must validate the file itself.
- An optional root-level `"hdr-preset"` block (`id`, `iterations`, `items[{iterations,
  controls}]`, 2–6 items) programs the firmware HDR sequence (src:`json_loader.hpp#L561-L606`, `#L700-L768`).

Key → field map (src:`src/ds/advanced_mode/json_loader.hpp#L295-L450`). Field values are scaled
by `scale` on load and divided on save. Integer fields are rounded (`floor(scale*v + 0.5)`).

| Group | JSON keys (→ struct field) |
|---|---|
| depth_control | `param-robbinsmonroincrement`→plusIncrement, `-robbinsmonrodecrement`→minusDecrement, `-medianthreshold`→deepSeaMedianThreshold, `-minscorethresha`→scoreThreshA, `-maxscorethreshb`→scoreThreshB, `-texturedifferencethresh`, `-texturecountthresh`, `-secondpeakdelta`→deepSeaSecondPeakThreshold, `-neighborthresh`→deepSeaNeighborThreshold, `-leftrightthreshold`→lrAgreeThreshold |
| rsm | `param-usersm` → **inverted** rsmBypass, `-rsmdiffthreshold`, `-rsmrauslodiffthreshold`, `-rsmremovethreshold` (**scale 168**) |
| rau_support_vector_control | `param-raumine/-rauminn/-rauminnssum/-raumins/-rauminw/-rauminwesum`, `-regionshrinku/-regionshrinkv` |
| color_control | `param-disableraucolor/-disablesadcolor/-disablesadnormalize/-disablesloleftcolor/-disableslorightcolor` |
| rau_thresholds_control | `param-regioncolorthresholdr/g/b` (**scale 1022**) |
| slo_color_thresholds_control | `param-scanlineedgetaur/g/b` |
| slo_penalty_control | `param-scanlinep1`, `-scanlinep1onediscon`, `-scanlinep1twodiscon`, `-scanlinep2`, `-scanlinep2onediscon`, `-scanlinep2twodiscon` |
| hdad | `param-lambdaad`, `param-lambdacensus`, `ignoreSAD` (no prefix) |
| color_correction | `aux-param-colorcorrection1..12` (written); `param-colorcorrection1..12` read-only duplicates |
| depth_table | `param-depthunits` (alias `param-zunits`), `param-depthclampmin/max` (aliases `aux-param-…`), `param-disparitymode`, `param-disparityshift` (alias `aux-…`) |
| ae_control | `param-autoexposure-setpoint` (alias `aux-…`) |
| census | `param-censusenablereg-udiameter/-vdiameter` (aliases `param-censususize/-censusvsize`) |
| amp_factor | `param-amplitude-factor` (only when FW supports it, ≥ 5.11.9.0 on D400) |
| ignored on load | `param-regionspatialthresholdu/v`, `aux-param-disparitymultiplier`, `stream-depth-format`, `stream-ir-format`, `stream-width`, `stream-height`, `stream-fps` |
| sensor options | `controls-laserstate` ("off"/"on"/"auto"), `controls-laserpower`, `controls-autoexposure-manual`, `controls-autoexposure-auto` ("True"/"False"), `controls-depth-gain`, `controls-depth-white-balance-auto`, `controls-color-*` (exposure, autoexposure, backlight-compensation, brightness, contrast, gain, gamma, hue, saturation, sharpness, power-line-frequency, white-balance-manual/-auto) |

So a preset file is **not** only advanced controls: it also sets ordinary options (laser,
exposure, gain, color image controls). Those are the same controls `rs config` already writes.

### Named (firmware) presets vs files

`rs.option.visual_preset` on the depth sensor (`rs.rs400_visual_preset`: custom, default, hand,
high_accuracy, high_density, medium_density, remove_ir_pattern, edge_enhancement; verified) is
registered **only while advanced mode is enabled**. Setting it makes librealsense apply hard-coded
group values that depend on the active stream resolution (src:`src/ds/advanced_mode/advanced_mode.cpp#L17-L26`,
`#L127-L253`, src:`src/ds/advanced_mode/presets.cpp`). The JSON files on the
[Visual Presets wiki page](https://github.com/IntelRealSense/librealsense/wiki/D400-Series-Visual-Presets)
are the same presets in legacy flat format. `restore.py` already treats `visual_preset` as the
control written first.

## 3. Parameter groups

Every group struct is in src:`include/librealsense2/h/rs_advanced_mode_command.h#L14-L128`. The
Python bindings are in src:`wrappers/python/pyrs_advanced_mode.cpp`. All fields are `uint32_t`
unless noted. Python sees them as `int`/`float`, and assigning a float, a negative value, or a
value ≥ 2³² to a `uint32` attribute raises `TypeError` (verified).

| `am.keys()` name (get_/set_ suffix) | Python struct | Fields |
|---|---|---|
| `depth_control` | `STDepthControlGroup` | plusIncrement, minusDecrement, deepSeaMedianThreshold, scoreThreshA, scoreThreshB, textureDifferenceThreshold, textureCountThreshold, deepSeaSecondPeakThreshold, deepSeaNeighborThreshold, lrAgreeThreshold |
| `rsm` | `STRsm` | rsmBypass, diffThresh *(float)*, sloRauDiffThresh *(float)*, removeThresh |
| `rau_support_vector_control` | `STRauSupportVectorControl` | minWest, minEast, minWEsum, minNorth, minSouth, minNSsum, uShrink, vShrink |
| `color_control` | `STColorControl` | disableSADColor, disableRAUColor, disableSLORightColor, disableSLOLeftColor, disableSADNormalize |
| `rau_thresholds_control` | `STRauColorThresholdsControl` | rauDiffThresholdRed, rauDiffThresholdGreen, rauDiffThresholdBlue |
| `slo_color_thresholds_control` | `STSloColorThresholdsControl` | diffThresholdRed, diffThresholdGreen, diffThresholdBlue |
| `slo_penalty_control` | `STSloPenaltyControl` | sloK1Penalty, sloK2Penalty, sloK1PenaltyMod1, sloK2PenaltyMod1, sloK1PenaltyMod2, sloK2PenaltyMod2 |
| `hdad` | `STHdad` | lambdaCensus *(float)*, lambdaAD *(float)*, ignoreSAD |
| `color_correction` | `STColorCorrection` | colorCorrection1 … colorCorrection12 *(all float)* |
| `depth_table` | `STDepthTableControl` | depthUnits, depthClampMin *(int32)*, depthClampMax *(int32)*, disparityMode, disparityShift *(int32)* |
| `ae_control` | `STAEControl` | meanIntensitySetPoint |
| `census` | `STCensusRadius` | uDiameter, vDiameter |
| `amp_factor` | `STAFactor` | `a_factor` in Python (C field `amplitude`) *(float)* |

That is 13 groups and 63 fields (verified). The Python method names differ from the C++ internals
(`get_census` vs `get_census_radius`, `get_depth_table` vs `get_depth_table_control`). Use the
Python names. `am.keys()` lists exactly the 13 above (verified).

**Modes and ranges**: `get_<group>(mode)` with `0` = current, `1` = minimum, `2` = maximum returns
the same struct, so each field has its own min and max (`RS2_ADVANCED_MODE_MODES 3`,
src:`include/librealsense2/h/rs_advanced_mode_command.h#L130-L131`;
src:`doc/rs400/rs400_advanced_mode.md#L211-L227`). The mode goes to the firmware as a `GET_ADV`
parameter (src:`src/core/advanced_mode.h#L262-L274`). There is **no step and no default** per
field. Floats are quantized by the firmware: the upstream test uses 1.1875 because "1.2 was out
of step" (src:`unit-tests/live/options/pytest-advanced-mode.py#L87`), so a read-back can differ
from the value written (*hardware-only*).

**Missing ranges**: "A group whose min/max FW does not report (hdad, and ae on some devices) fails
the query". `get_all_controls()` catches that and repeats the current value as min and max
(src:`src/ds/advanced_mode/advanced_mode.cpp#L343-L382`). A direct `get_hdad(1)` raises
(*hardware-only*). `get_amp_factor` returns 0 without asking the FW when the feature is
unsupported.

**Bulk read**: `am.get_all_controls()` returns `STAdvancedModeControls`: for each of the 13
groups, a read-only list `[current, min, max]` (`ac.depth_control[1]` is the min struct). It
reads everything under one depth-sensor bulk operation, because "each standalone GET_ADV powers
the depth sensor up and back down again". Prefer it for any listing.
`STAdvancedModeControls` has **no Python constructor** (verified)
(src:`wrappers/python/pyrs_advanced_mode.cpp#L259-L283`).

**Mapping interface** (2.59.1 bindings, src:`wrappers/python/pyrs_advanced_mode.cpp#L16-L41`, `#L320-L349`):
- `am.keys()` → group names; `am["rsm"]` ≡ `get_rsm(0)`; `am["rsm", 2]` ≡ `get_rsm(2)`;
  `am["rsm"] = struct` ≡ `set_rsm(struct)`.
- Each struct: `s.keys()` → field names; `s["diffThresh"]`; `s["removeThresh"] = 12.6` **rounds**
  to 13 for int fields (verified), where attribute assignment raises `TypeError`. An unknown key
  raises `AttributeError` (verified).
- `__repr__` of `STDepthControlGroup` omits `plusIncrement` (binding bug, verified). Don't use
  `repr` for output.
- `set_<group>` writes the **whole struct**, so editing one field is read, modify, write. Any
  set moves `visual_preset` to `custom` (src:`unit-tests/live/options/pytest-presets.py#L45-L58`).
  `set` raises when the device is "blocked" (during on-chip calibration)
  (src:`src/core/advanced_mode.h#L248-L252`).

Get/set calls don't check `is_enabled()` on the host: they go to the firmware, which is expected
to reject them when advanced mode is off. The error text is *hardware-only* and unverified.

## 4. On a software device (the simulated D435)

Verified with throwaway scripts against `d435()` from `realsense_cli/driver/software.py`:

| Call | Result |
|---|---|
| `rs.rs400_advanced_mode(cam.device)`, `rs.serializable_device(cam.device)` | construct OK (no error) |
| `.is_enabled()`, `.toggle_advanced_mode(True)`, `.get_depth_control(0/1)`, `.set_depth_control(...)`, `.get_all_controls()`, `am["depth_control"]`, `.serialize_json()`, `.load_json("{}")` | `RuntimeError: null pointer passed for argument "dev"` |
| `am.keys()` | OK, the 13 names (pure Python, never reaches the device) |
| `rs.STDepthControlGroup()` and the other 12 group structs | construct OK, all fields 0, attribute and mapping access work |
| `rs.STAdvancedModeControls()` | `TypeError: No constructor defined!` |
| `dev.supports(rs.camera_info.advanced_mode)` on the mock D435 | `False` (not registered), but `register_info(rs.camera_info.advanced_mode, "YES")` works on a software device |
| `software_sensor.add_option(rs.option.visual_preset, range, True)` | works: plain settable float, no preset semantics, no value descriptions |

Why: `software_device` is a C++ class that implements neither `ds_advanced_mode_interface` nor
`serializable_interface`, and Python can't add a librealsense extension to it. Advanced mode
needs a device with a `debug_interface` and a real firmware (`send_receive` of
`GET_ADV`/`SET_ADV`/`EN_ADV`) (src:`src/ds/advanced_mode/advanced_mode.cpp#L46-L60`).
**Nothing in advanced mode is reachable through `rs.software_device`.**

### A mock-testable path

1. **One seam in the real driver.** `Realsense` gets its advanced-mode object from one method,
   e.g. `_advanced_mode(device)`. For a real device this returns `rs.rs400_advanced_mode(dev)`,
   which is detected by catching the null-pointer `RuntimeError` on `is_enabled()`. For an
   injected `SoftwareCamera` it returns the camera's Python fake, and `None` when the spec says
   the camera has no advanced mode. This follows the existing pattern: `Realsense(devices=[...])`
   already special-cases injected devices for `play()`.
2. **A `FakeAdvancedMode` in `driver/software.py`** with the same duck-typed surface the driver
   uses: `is_enabled()`, `toggle_advanced_mode()`, `get_<group>(mode)` / `set_<group>(struct)`
   (or the `keys()`/`[]` mapping), `get_all_controls()`, `serialize_json()`, `load_json()`. It holds
   **real pyrealsense2 structs** (`rs.STDepthControlGroup()` etc.) for current, min and max, so the
   driver's struct ↔ dict code runs unmodified. `get_all_controls()` returns a small Python
   object with `.depth_control == [cur, min, max]`, because the real type can't be constructed.
   It raises `RuntimeError` like the firmware for min/max on `hdad`, and for any get/set while
   disabled. It sets the camera's `visual_preset` option to `custom` on each set.
3. **Preset JSON in the fake**: implement the documented envelope, the key table above (including
   the scales and the `usersm` inversion), the product-line check and the unknown-key failure.
   Keep it to keys the mock D435 has. It can map `controls-laserpower` etc. onto the software
   sensor's real options, so `load` changing an option is visible through `rs config get`. The
   real `load_json` can't be cross-checked without hardware, so tests of the fake prove the CLI's
   handling, not librealsense's parsing.
4. **Toggle in the fake**: flip the flag and simulate the reset. The repo's reset path is the
   model for how far a disconnect can be simulated on a software device; check `rs reset`'s
   mock behaviour when designing this.
5. **Mock D435 fidelity**: register `camera_info.advanced_mode` ("YES"), and add `visual_preset`
   to the Stereo Module only when the fake is enabled. That mirrors a D400, where it exists only
   in advanced mode.

Hardware-marked tests (`-m hardware`) would then cover the real `rs400_advanced_mode` path:
toggle and reconnect, `serialize_json` → `load_json` round trip, and the `get_hdad(1)` failure.

## Open questions (not answerable without hardware or a design decision)

- The exact error a D400 firmware returns for `get_<group>`/`set_<group>` while advanced mode is
  off, and whether reading min/max needs advanced mode at all.
- Whether `load_json` or `set_<group>` while streaming fails, or only "isn't recommended", and how
  long writes take to take effect.
- Whether D500 `toggle_advanced_mode(False)` errors or silently resets.
- Whether the CLI's preset format should be librealsense's JSON as is (interoperable with the
  Viewer) or a wrapper (e.g. one that also records `rs config` controls). Decide in #40.
