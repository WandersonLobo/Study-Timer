"""Contratos do preparador de aceite; não executam VM nem transições de energia."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "windows_acceptance.ps1"
VM_ID = "15f329ee-bad1-42d9-880d-b344538c88c5"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell indisponível")


def invoke(
    tmp_path: Path,
    *,
    evidence: dict[str, Any] | None = None,
    expected_hash: str | None = None,
) -> tuple[int, dict[str, Any]]:
    archive = tmp_path / "candidate.zip"
    archive.write_bytes(b"synthetic package, never executed")
    package_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    output = tmp_path / "result"
    assert POWERSHELL is not None
    command = [
        POWERSHELL,
        "-NoProfile",
        "-File",
        str(SCRIPT),
        "-Mode",
        "Plan" if evidence is None else "ValidateEvidence",
        "-VmId",
        VM_ID,
        "-Archive",
        str(archive),
        "-ExpectedSha256",
        expected_hash or package_hash,
        "-OutputDirectory",
        str(output),
    ]
    if evidence is not None:
        record = tmp_path / "evidence.json"
        record.write_text(json.dumps(evidence), encoding="utf-8")
        command.extend(["-EvidenceFile", str(record)])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    result = output / "windows-acceptance.json"
    assert result.exists(), completed.stderr
    return completed.returncode, json.loads(result.read_text(encoding="utf-8-sig"))


def complete_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in plan["cases"]:
        result: dict[str, Any] = {"id": case["id"], "status": "passed"}
        flags = (
            (
                "hash_verified",
                "types_cycle",
                "history_filters",
                "theme_persisted",
                "reopen_preserved",
                "migration_preserved",
                "directory_replacement",
            )
            if case["kind"] == "distribution"
            else (
                "guest_transition_confirmed",
                "power_event_received",
                "sleep_excluded",
                "paused_after_resume",
                "explicit_resume_only",
                "reopen_preserved",
            )
        )
        result.update(dict.fromkeys(flags, True))
        if case["kind"] == "guest-power":
            result.update(
                transition="guest_s4" if case["power"] == "hibernate" else "guest_sleep",
                open_intervals_after=0,
                frozen_total_s=20,
                total_after_resume_s=20,
                total_after_observation_s=20,
            )
        results.append(result)
    return {
        "schema_version": 1,
        "vm_id": VM_ID,
        "package_sha256": plan["package_sha256"],
        "environment": {
            "windows": "Windows 11",
            "architecture": "x64",
            "python_absent": True,
            "offline": True,
            "isolated_profile": True,
            "powercfg_checked": True,
        },
        "results": results,
    }


def test_plan_is_pending_and_covers_full_matrix(tmp_path: Path) -> None:
    exit_code, result = invoke(tmp_path)
    assert exit_code == 2
    assert result["status"] == "pending"
    assert result["hardware_certified"] is False
    assert len(result["cases"]) == len({case["id"] for case in result["cases"]}) == 33
    assert all(case["status"] == "pending" for case in result["cases"])


def test_bad_hash_cannot_prepare_acceptance(tmp_path: Path) -> None:
    exit_code, result = invoke(tmp_path, expected_hash="0" * 64)
    assert exit_code == 1
    assert result["reason_code"] == "PACKAGE_HASH_MISMATCH"


def test_partial_evidence_remains_pending(tmp_path: Path) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    evidence["results"] = evidence["results"][:1]
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 2
    assert result["reason_code"] == "COVERAGE_INCOMPLETE"


def test_complete_records_only_validate_operator_evidence(tmp_path: Path) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    evidence["private_note"] = "never publish arbitrary operator text"
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 0
    assert result["status"] == "evidence-complete"
    assert result["hardware_certified"] is False
    assert "private_note" not in result


@pytest.mark.parametrize("flag_value", [False, "true", 1, None])
def test_environment_flags_require_boolean_true(tmp_path: Path, flag_value: object) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    evidence["environment"]["isolated_profile"] = flag_value
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 1
    assert result["reason_code"] == "ENVIRONMENT_UNVERIFIED"


@pytest.mark.parametrize("flag_value", [False, "true", 1, None])
def test_passed_case_requires_boolean_evidence(tmp_path: Path, flag_value: object) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    evidence["results"][1]["guest_transition_confirmed"] = flag_value
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 1
    assert result["reason_code"] == "PASSED_CASE_WITHOUT_EVIDENCE"


@pytest.mark.parametrize("field", ["open_intervals_after", "frozen_total_s"])
@pytest.mark.parametrize("invalid", [None, True, "0", -1, 0.5])
def test_power_numbers_are_required_nonnegative_integers(
    tmp_path: Path, field: str, invalid: object
) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    if invalid is None:
        del evidence["results"][1][field]
    else:
        evidence["results"][1][field] = invalid
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 1
    assert result["reason_code"] == "POWER_RESULT_INCONSISTENT"


def test_sleep_time_cannot_be_added_to_frozen_total(tmp_path: Path) -> None:
    _, plan = invoke(tmp_path)
    evidence = complete_evidence(plan)
    evidence["results"][1]["total_after_resume_s"] = 50
    evidence["results"][1]["total_after_observation_s"] = 50
    exit_code, result = invoke(tmp_path, evidence=evidence)
    assert exit_code == 1
    assert result["reason_code"] == "POWER_RESULT_INCONSISTENT"
