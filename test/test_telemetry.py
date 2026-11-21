"""Reported measurements and native Claude results retain their original coverage."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.telemetry import Usage, read_telemetry

_MODEL_USAGE = {
    "inputTokens": 2,
    "outputTokens": 3,
    "cacheReadInputTokens": 4,
    "cacheCreationInputTokens": 5,
}


def test_claude_uses_all_models_and_excludes_estimated_usd(tmp_path: Path) -> None:
    result = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.125,
        "modelUsage": {"main": _MODEL_USAGE, "subagent": _MODEL_USAGE},
    }
    usage, reason = read_telemetry(tmp_path / "absent.json", json.dumps(result).encode())
    assert reason is None
    assert usage == Usage(tokens=28)


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"type": "result", "subtype": "error_during_execution", "modelUsage": {"main": _MODEL_USAGE}}, "crash"),
        ({"type": "result", "is_error": True, "modelUsage": {"main": {"inputTokens": 10}}}, "harness_error"),
        ({"type": "result", "modelUsage": {"main": None}}, None),
        ({"type": "other", "modelUsage": {"main": _MODEL_USAGE}}, None),
    ],
)
def test_partial_or_unreliable_native_usage_stays_unknown(
    tmp_path: Path, result: dict[str, object], reason: str | None
) -> None:
    assert read_telemetry(tmp_path / "absent.json", json.dumps(result).encode()) == (Usage(), reason)


def test_token_total_outside_json_integer_range_does_not_hide_other_measurements(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"tokens": 9007199254740992, "cost_usd": 0.25}', encoding="utf-8")
    result = {
        "type": "result",
        "modelUsage": {"main": {**_MODEL_USAGE, "inputTokens": 9007199254740991}},
    }
    assert read_telemetry(report, json.dumps(result).encode()) == (Usage(cost_usd=0.25), None)


def test_oversized_json_integer_only_invalidates_its_own_measurement(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"tokens": ' + "9" * 4301 + ', "cost_usd": 0.25, "quota_percent": 12}', encoding="utf-8")
    assert read_telemetry(report, b"") == (Usage(cost_usd=0.25, quota_percent=12), None)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes require POSIX")
def test_reading_a_pipe_report_returns_without_blocking(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    os.mkfifo(report)
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; from forge.telemetry import read_telemetry, Usage; "
                "import sys; assert read_telemetry(Path(sys.argv[1]), b'') == (Usage(), None)"
            ),
            str(report),
        ],
        check=True,
        timeout=3,
    )


def test_oversized_report_is_uncovered(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"tokens": 10}' + " " * (1024 * 1024), encoding="utf-8")
    assert read_telemetry(report, b"") == (Usage(), None)
