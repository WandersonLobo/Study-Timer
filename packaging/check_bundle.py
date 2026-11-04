"""Rejeita dados pessoais e caminhos da máquina de build no pacote final."""

import argparse
import os
from pathlib import Path

FORBIDDEN_SUFFIXES = {".db", ".csv", ".log", ".bak", ".pending", ".lock"}
FORBIDDEN_DIRECTORIES = {"logs", "backups", ".venv", ".git", "__pycache__"}
# Texto público de ntpath.splitroot, incluído no CPython oficial. A exceção é
# para a expressão completa, nunca para esse usuário, arquivo ou DLL em geral.
PUBLIC_STDLIB_EXAMPLE = "splitroot('C:/Users/Barney') == ('C:', '/', 'Users/Barney')"


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
    private_needles: list[bytes] = []
    for private_path in private_paths:
        if private_path:
            for spelling in (private_path, private_path.replace("\\", "/")):
                private_needles.extend(
                    (spelling.lower().encode(), spelling.lower().encode("utf-16-le"))
                )
    examples = [
        PUBLIC_STDLIB_EXAMPLE.lower().encode(encoding) for encoding in ("utf-8", "utf-16-le")
    ]
    overlap = max(map(len, needles + private_needles + examples))

    def inspect(content: bytes, first: int, following: int) -> None:
        # O perfil real é rejeitado mesmo se coincidir com um exemplo público.
        if any(needle in content for needle in private_needles):
            raise ValueError("O pacote contém um caminho privado da máquina de build.")
        for example in examples:
            content = content.replace(example, b"\0" * len(example))
        for needle in needles:
            position = content.find(needle, first)
            if first <= position < following:
                raise ValueError("O pacote contém um caminho privado da máquina de build.")

    for path in bundle_dir.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("O pacote contém link simbólico.")
        if not path.is_file():
            continue
        if is_private_file(path.relative_to(bundle_dir)):
            raise ValueError("O pacote contém banco, log, backup ou outro arquivo privado.")
        # Guarda contexto à esquerda e olha à frente antes de aceitar a exceção;
        # exemplos e caminhos privados podem atravessar a fronteira de um bloco.
        pending = b""
        offset = checked_until = 0
        with path.open("rb") as source:
            if source.read(16) == b"SQLite format 3\x00":
                raise ValueError("O pacote contém banco SQLite renomeado.")
            source.seek(0)
            while chunk := source.read(1_048_576):
                pending += chunk.lower()
                following = max(0, len(pending) - overlap)
                inspect(pending, max(0, checked_until - offset), following)
                checked_until = offset + following
                remove = max(0, len(pending) - 2 * overlap)
                pending = pending[remove:]
                offset += remove
            inspect(pending, max(0, checked_until - offset), len(pending))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    arguments = parser.parse_args()
    check_bundle(arguments.bundle, (os.environ.get("USERPROFILE", ""),))
