from __future__ import annotations


def format_partition_label(partition_key: str) -> str:
    key = str(partition_key or "").strip()
    if not key or key == "global":
        return "Global"
    parts = []
    for raw_part in key.split("|"):
        part = str(raw_part or "").strip()
        if not part:
            continue
        if ":" in part:
            _field, value = part.split(":", 1)
            part = value.strip()
        elif "=" in part:
            _field, value = part.split("=", 1)
            part = value.strip()
        parts.append(part)
    return " | ".join(parts) or key


def program_unit_display_name(unit) -> str:
    name = str(getattr(unit, "nom", "") or "").strip()
    partition_key = str(getattr(unit, "partition_key", "") or "").strip()
    partition_label = format_partition_label(partition_key)
    if name and partition_key and partition_key != "global" and partition_key in name:
        return name.replace(partition_key, partition_label)
    return name


__all__ = ["format_partition_label", "program_unit_display_name"]
