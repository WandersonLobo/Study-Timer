"""Gera locks com hashes das wheels previamente baixadas do PyPI oficial."""

import argparse
import hashlib
from pathlib import Path


def generate_locks(wheel_dir: Path, project_root: Path) -> None:
    """Exige versões exatas e hashes de todos os artefatos para Windows x64/3.12."""
    hashes: dict[tuple[str, str], str] = {}
    for wheel in wheel_dir.glob("*.whl"):
        name, version, *_ = wheel.name.split("-")
        key = (name.lower().replace("_", "-"), version)
        if key in hashes:
            raise ValueError("Use uma pasta contendo uma única wheel por versão e pacote.")
        hashes[key] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    for source_name in ("requirements.in", "requirements-dev.in"):
        source = project_root / source_name
        lines = [
            "# Gerado por packaging/lock_dependencies.py; não editar manualmente.",
            "# Artefatos: CPython 3.12, Windows x64. Instalar com --require-hashes.",
        ]
        for raw_line in source.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                lines.append(line.replace(".in", ".txt"))
                continue
            requirement = line.split(";", 1)[0].strip()
            name, version = requirement.split("==")
            key = (name.lower().replace("_", "-"), version)
            digest = hashes[key]
            lines.append(f"{line} --hash=sha256:{digest}")
        source.with_suffix(".txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", type=Path)
    arguments = parser.parse_args()
    generate_locks(arguments.wheels, Path(__file__).resolve().parent.parent)
