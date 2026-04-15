"""Shared formatting helpers."""

from __future__ import annotations


def format_bytes(bytes_count: int, decimals: int = 1) -> str:
    """Format a byte count as human-readable text."""
    if bytes_count <= 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(bytes_count)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.{decimals}f} {units[unit_index]}"
