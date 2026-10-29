"""Bloqueio de instância por perfil Windows, liberado pelo sistema ao encerrar."""

import errno
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self


class AlreadyRunningError(RuntimeError):
    """Indica que outra instância possui o arquivo de bloqueio do perfil."""


class SingleInstance:
    """Mantém um lock de byte Windows sem arquivos de PID obsoletos."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> Self:
        """Obtém o lock antes de acessar banco e arquivos de log compartilhados."""
        import msvcrt

        handle = self._lock_path.open("a+b")
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AlreadyRunningError("O StudyTimer já está aberto neste perfil.") from None
            raise
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Libera o handle; o Windows também o libera em encerramentos abruptos."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
