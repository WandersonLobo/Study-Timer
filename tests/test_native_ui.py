"""Cada cenário Tk usa seu próprio processo e diretório de dados temporário."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.native_manifest import NATIVE_SCENARIOS

pytestmark = [
    pytest.mark.native_ui,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("STUDYTIMER_NATIVE_UI") != "1",
        reason="Aceite Tk real exige Windows e STUDYTIMER_NATIVE_UI=1.",
    ),
]


def run_scenario(scenario: str, mode: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    # A captura visual tem quatro subprocessos, cada um com prazo próprio de 20 s.
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.native_ui_scenarios", scenario, str(tmp_path), mode],
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=120 if scenario == "visual" else 45)
    except subprocess.TimeoutExpired:
        # O redirector da venv pode ter filhos que ainda mantêm os pipes abertos.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        process.kill()
        process.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scenario", NATIVE_SCENARIOS)
def test_native_scenario(scenario: str, mode: str, tmp_path: Path) -> None:
    # CTk/Tcl mantêm estado global. Produção também cria uma raiz por processo.
    result = run_scenario(scenario, mode, tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    if result.stdout.strip():
        print(result.stdout.strip())
    if scenario == "types_themes":
        reopened = run_scenario("reopened_types", mode, tmp_path)
        assert reopened.returncode == 0, reopened.stderr + reopened.stdout
