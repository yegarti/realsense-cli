"""
Resolving the advanced-control names `rs advanced` takes: `group.field` with the SDK's names
(`rsm.diffThresh`), or a bare group for all its fields, either case-insensitive. And checking
the values `rs advanced set` writes.
"""

import math
import struct

from realsense_cli.errors import InvalidValue, UnknownAdvancedControl
from realsense_cli.types import AdvancedControl


def resolve_names(groups: dict[str, list[str]], names: list[str]) -> list[str]:
    """
    The `group.field` names NAMES pick out of GROUPS (each group's fields), spelled as the SDK
    spells them, in the order given and without repeats; every field when NAMES is empty.
    Raises `UnknownAdvancedControl` listing the valid groups, or the group's valid fields
    """
    if not names:
        names = list(groups)
    by_lower = {group.lower(): group for group in groups}
    resolved: dict[str, None] = {}
    for name in names:
        group_name, dot, field_name = name.partition(".")
        group = by_lower.get(group_name.lower())
        if group is None:
            raise UnknownAdvancedControl(
                f"Unknown advanced-control group '{group_name}'. "
                f"Valid groups: {', '.join(groups)}"
            )
        fields = groups[group]
        if not dot:
            resolved.update(dict.fromkeys(f"{group}.{f}" for f in fields))
            continue
        field = next((f for f in fields if f.lower() == field_name.lower()), None)
        if field is None:
            raise UnknownAdvancedControl(
                f"Advanced-control group '{group}' has no field '{field_name}'. "
                f"Valid fields: {', '.join(fields)}"
            )
        resolved[f"{group}.{field}"] = None
    return list(resolved)


def parse_assignments(groups: dict[str, list[str]], assignments: list[str]) -> dict[str, float]:
    """
    The `group.field` names and values ASSIGNMENTS (`NAME=VALUE`) give, names spelled as the
    SDK spells them; a later value for the same field wins. Raises `InvalidValue` for an
    assignment that doesn't parse, and `UnknownAdvancedControl` for a name that isn't one field
    """
    values = {}
    for assignment in assignments:
        name, eq, text = assignment.partition("=")
        try:
            value = float(text) if eq else math.nan
        except ValueError:
            value = math.nan
        if not math.isfinite(value):
            raise InvalidValue(
                f"Failed to parse '{assignment}', expected NAME=VALUE with a numeric VALUE"
            )
        resolved = resolve_names(groups, [name])
        if "." not in name:
            group = resolved[0].partition(".")[0]
            raise UnknownAdvancedControl(
                f"'{name}' is a group; set one of its fields as group.field. "
                f"Valid fields: {', '.join(groups[group])}"
            )
        values[resolved[0]] = value
    return values


def check_values(
    controls: dict[str, AdvancedControl], values: dict[str, float], ranges: bool
) -> None:
    """
    Check VALUES against their CONTROLS: an int field takes a whole number, and with RANGES, a
    value within the field's min and max where it has them. Raises `InvalidValue`
    """
    for name, value in values.items():
        control = controls[name]
        vtype = control.vtype.__name__
        if control.vtype is int and not float(value).is_integer():
            raise InvalidValue(f"Advanced control '{name}' takes an int, not {_number(value)}")
        low, high = control.min_value, control.max_value
        if not ranges or low is None or high is None:
            continue
        if control.vtype is float:
            # a float field holds a float32, whose range reads back as the shortest decimal
            in_range = _float32(low) <= _float32(value) <= _float32(high)
        else:
            in_range = low <= value <= high
        if in_range:
            continue
        raise InvalidValue(
            f"Advanced control '{name}' takes {'an' if vtype == 'int' else 'a'} {vtype} "
            f"from {_number(low)} to {_number(high)}, not {_number(value)}; "
            "--no-validate skips the range check"
        )


def _float32(value: float) -> float:
    """VALUE rounded to a float32; infinite beyond the float32 range"""
    try:
        return struct.unpack("f", struct.pack("f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _number(value: float) -> str:
    """VALUE as a user would type it: 200, not 200.0"""
    whole = float(value).is_integer() and abs(value) < 1e16
    return str(int(value)) if whole else str(value)
