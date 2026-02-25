# path: cerebro/core/reporting/__init__.py
"""
Reporting helpers for CEREBRO.

- json_report: write scan + delete plan as structured JSON for auditing.
- script_report: emit shell scripts (bash / PowerShell) for reproducible cleanup.

These modules are optional and safe to import from workers (no Qt usage).
"""

from .json_report import write_json_report
from .script_report import write_cleanup_scripts

__all__ = ["write_json_report", "write_cleanup_scripts"]
