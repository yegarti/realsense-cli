"""
Checking a preset file before `rs preset load` hands it to the SDK.

librealsense checks little itself: a value it can't parse silently loads as 0. So `rs` checks
the JSON, the envelope (schema version 1 with `parameters`, or the legacy flat format) and that
every value is a number or one of the names the SDK writes. Unknown keys and a product-line
mismatch are left to the SDK, which rejects them before writing anything.
"""

import json
import re
from pathlib import Path
from typing import Any

from realsense_cli.errors import InvalidValue

SCHEMA_VERSION = 1

# The names librealsense writes for a control's values (`controls-laserstate`, `*-auto`)
VALUE_NAMES = ("off", "on", "auto", "True", "False")

# What the SDK's `atof` reads in full
_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def parameters(preset: Any) -> dict[str, Any] | None:
    """
    The preset keys of PRESET, a decoded preset file: its `parameters` under the schema-1
    envelope, the whole object in the legacy flat format. None when it's neither
    """
    if not isinstance(preset, dict):
        return None
    has_version, has_parameters = "schema version" in preset, "parameters" in preset
    if not has_version and not has_parameters:
        return preset
    if has_version and has_parameters and isinstance(preset["parameters"], dict):
        return preset["parameters"]
    return None


def valid_value(value: Any) -> bool:
    """Whether the SDK reads VALUE as what it says: a number, or one of `VALUE_NAMES`"""
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    return isinstance(value, str) and (value in VALUE_NAMES or bool(_NUMBER.fullmatch(value)))


def read_preset(path: Path, validate: bool = True) -> str:
    """
    The preset file at PATH, as written, after checking it holds a preset; with VALIDATE, also
    that every value is one the SDK reads. Raises `InvalidValue` listing every bad key
    """
    try:
        text = path.read_text()
        preset = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidValue(f"'{path}' is not valid JSON: {e}") from None
    keys = parameters(preset)
    if keys is None or not isinstance(preset, dict):
        raise InvalidValue(
            f"'{path}' is not a preset file: it needs \"schema version\" {SCHEMA_VERSION} "
            'and "parameters", or preset keys alone (the legacy flat format)'
        )
    if preset.get("schema version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise InvalidValue(
            f"'{path}' has schema version {json.dumps(preset['schema version'])}; "
            f"only {SCHEMA_VERSION} is supported"
        )
    if validate:
        bad = [
            f"{key} ({json.dumps(value)})"
            for key, value in keys.items()
            if not valid_value(value)
        ]
        if bad:
            raise InvalidValue(
                f"'{path}' has invalid values for {', '.join(bad)}. A value must be a number "
                f"or one of {', '.join(VALUE_NAMES)}; --no-validate loads them anyway"
            )
    return text


def preset_changes(before: str, after: str) -> list[dict[str, str | None]]:
    """
    The preset keys whose value differs between BEFORE and AFTER, two preset files the SDK
    wrote, in AFTER's order: `{"key", "old", "new"}`, with None for a key one of them lacks
    """
    old, new = json.loads(before)["parameters"], json.loads(after)["parameters"]
    keys = list(new) + [key for key in old if key not in new]
    return [
        {"key": key, "old": old.get(key), "new": new.get(key)}
        for key in keys
        if old.get(key) != new.get(key)
    ]
