"""Cada cenário Tk usa seu próprio processo e diretório de dados temporário."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.native_ui,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("STUDYTIMER_NATIVE_UI") != "1",
        reason="Aceite Tk real exige Windows e STUDYTIMER_NATIVE_UI=1.",
    ),
]


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(
    "scenario",
    [
        "cycle",
        "recovery",
        "offline_backup",
        "history_1000",
        "types_themes",
        "dialog_errors",
        "scaling",
    ],
)
def test_native_scenario(scenario: str, mode: str, tmp_path: Path) -> None:
    # CTk/Tcl mantêm estado global. Produção também cria uma raiz por processo.
    result = subprocess.run(
        [sys.executable, "-m", "tests.native_ui_scenarios", scenario, str(tmp_path), mode],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    if result.stdout.strip():
        print(result.stdout.strip())
    if scenario == "types_themes":
        reopened = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.native_ui_scenarios",
                "reopened_types",
                str(tmp_path),
                mode,
            ],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert reopened.returncode == 0, reopened.stderr + reopened.stdout
