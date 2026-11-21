"""Read reported step telemetry without deriving it from prices or quotas."""

import json
import os
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

type ExitReason = Literal["ok", "timeout", "crash", "gate_fail", "harness_error"]

_MAX_REPORT_BYTES = 64 * 1024
_MAX_MEASUREMENT_DIGITS = len(str(int(sys.float_info.max)))
_MAX_TOKEN_COUNT = (1 << 53) - 1  # Exact in JSON consumers that use binary64 numbers.


@dataclass(frozen=True)
class Usage:
    """Measurements for one attempt. None indicates missing coverage."""

    tokens: int | None = None
    cost_usd: float | None = None
    quota_percent: float | None = None

    def manifest(self) -> dict[str, object]:
        values = asdict(self)
        return {**values, "coverage": {unit: value is not None for unit, value in values.items()}}


def _parse_integer(raw: str) -> int | None:
    return int(raw) if len(raw.removeprefix("-")) <= _MAX_MEASUREMENT_DIGITS else None


def _json_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw, parse_int=_parse_integer)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_report(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return {}
        with os.fdopen(os.open(path, flags), "rb") as stream:
            # The harness can replace the file between lstat and open.
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {}
            data = stream.read(_MAX_REPORT_BYTES + 1)
    except OSError:
        return {}
    return _json_object(data) if len(data) <= _MAX_REPORT_BYTES else {}


def _token_count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= _MAX_TOKEN_COUNT else None


def _measurement(value: object, maximum: float) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= maximum:
        return float(value)
    return None


def _claude_tokens(result: dict[str, object]) -> int | None:
    # modelUsage includes subagent usage. Crash results can carry zeroed counts.
    models = result.get("modelUsage")
    if result.get("subtype") == "error_during_execution" or not isinstance(models, dict) or not models:
        return None
    total = 0
    for model in models.values():
        if not isinstance(model, dict):
            return None
        for key in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"):
            count = _token_count(model.get(key))
            if count is None:
                return None
            total += count
    return _token_count(total)


def read_telemetry(path: Path, claude_stdout: bytes) -> tuple[Usage, ExitReason | None]:
    """Read a harness report and, when configured, Claude's single-shot JSON result."""
    report = _read_report(path)
    claude = _json_object(claude_stdout) if claude_stdout else {}
    if claude.get("type") != "result":
        claude = {}

    tokens = _token_count(report.get("tokens"))
    usage = Usage(
        tokens=tokens if tokens is not None else _claude_tokens(claude),
        cost_usd=_measurement(report.get("cost_usd"), sys.float_info.max),
        quota_percent=_measurement(report.get("quota_percent"), 100),
    )
    if report.get("exit_reason") == "gate_fail":
        return usage, "gate_fail"
    if claude.get("subtype") == "error_during_execution":
        return usage, "crash"
    if report.get("exit_reason") == "harness_error" or claude.get("is_error") is True:
        return usage, "harness_error"
    return usage, None
