"""Rejeita dados pessoais e caminhos da máquina de build no pacote final."""

import argparse
import os
from pathlib import Path

FORBIDDEN_SUFFIXES = {".db", ".csv", ".log", ".bak", ".pending", ".lock"}
FORBIDDEN_DIRECTORIES = {"logs", "backups", ".venv", ".git", "__pycache__"}


def is_private_file(path: Path) -> bool:
    """Identifica banco, backup, logs e exportações em qualquer subdiretório."""
    name = path.name.lower()
    return (
        path.suffix.lower() in FORBIDDEN_SUFFIXES
        or ".sqlite" in name
        or ".db-" in name
        or ".db." in name
        or ".corrupt" in name
        or name == ".env"
        or name.startswith(".env.")
        or bool(set(part.lower() for part in path.parts) & FORBIDDEN_DIRECTORIES)
    )


def check_bundle(bundle_dir: Path, private_paths: tuple[str, ...] = ()) -> None:
    """Impede empacotar arquivos privados e referências ao perfil do desenvolvedor.

    Args:
        bundle_dir: Diretório onedir já gerado, antes e depois do smoke test.
        private_paths: Caminhos pessoais adicionais que devem ser rejeitados.
    """
    if not bundle_dir.is_dir() or bundle_dir.is_symlink() or bundle_dir.is_junction():
        raise ValueError("Diretório de distribuição ausente.")
    patterns = (b"c:\\users\\", b"c:/users/", b"/users/", b"/home/")
    needles = list(patterns) + [pattern.decode("ascii").encode("utf-16-le") for pattern in patterns]
    for private_path in private_paths:
        if private_path:
            for spelling in (private_path, private_path.replace("\\", "/")):
                needles.extend((spelling.lower().encode(), spelling.lower().encode("utf-16-le")))
    for path in bundle_dir.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("O pacote contém link simbólico.")
        if not path.is_file():
            continue
        if is_private_file(path.relative_to(bundle_dir)):
            raise ValueError("O pacote contém banco, log, backup ou outro arquivo privado.")
        # Blocos sobrepostos encontram também padrões divididos na fronteira.
        overlap = max(map(len, needles))
        previous = b""
        with path.open("rb") as source:
            if source.read(16) == b"SQLite format 3\x00":
                raise ValueError("O pacote contém banco SQLite renomeado.")
            source.seek(0)
            while chunk := source.read(1_048_576):
                content = previous + chunk.lower()
                if any(needle in content for needle in needles):
                    raise ValueError("O pacote contém um caminho privado da máquina de build.")
                previous = content[-overlap:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    arguments = parser.parse_args()
    check_bundle(arguments.bundle, (os.environ.get("USERPROFILE", ""),))
