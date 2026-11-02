"""
Resolving the advanced-control names `rs advanced` takes: `group.field` with the SDK's names
(`rsm.diffThresh`), or a bare group for all its fields, either case-insensitive.
"""

from realsense_cli.errors import UnknownAdvancedControl


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
