"""Salva o último tick aceito em arquivo, fora da thread da janela."""

import json
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import astuple
from pathlib import Path

from app.models import ClockSnapshot

logger = logging.getLogger("studytimer.recovery")


class RecoveryPoint:
    """Mantém no máximo uma gravação pendente, sem bloquear o cronômetro."""

    def __init__(self, path: Path, worker: ThreadPoolExecutor) -> None:
        self._path = path
        self._worker = worker
        self._pending: Future[None] | None = None
        self._saved: ClockSnapshot | None = None

    def read(self) -> ClockSnapshot | None:
        """Lê um ponto completo. O repositório confere se o intervalo ainda está aberto."""
        try:
            values = json.loads(self._path.read_text(encoding="utf-8"))
            if (
                isinstance(values, list)
                and len(values) == 4
                and all(type(value) is int and -(2**63) <= value < 2**63 for value in values)
            ):
                return ClockSnapshot(*values)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            logger.warning("RECOVERY_POINT_READ_FAILED type=%s", type(error).__name__)
            return None
        logger.warning("RECOVERY_POINT_INVALID")
        return None

    def submit(self, snapshot: ClockSnapshot) -> None:
        """Envia somente o snapshot imutável, sem compartilhar SQLite ou Tk."""
        if self._pending is not None and not self._pending.done():
            return
        if snapshot != self._saved:
            self._pending = self._worker.submit(self._write, snapshot)

    def clear(self) -> None:
        """Descarta o ponto já processado quando o worker estiver ocioso."""
        try:
            self._path.unlink(missing_ok=True)
            self._path.with_suffix(".tmp.pending").unlink(missing_ok=True)
        except OSError as error:
            logger.warning("RECOVERY_POINT_CLEANUP_FAILED type=%s", type(error).__name__)

    def _write(self, snapshot: ClockSnapshot) -> None:
        temporary = self._path.with_suffix(".tmp.pending")
        try:
            with temporary.open("w", encoding="utf-8") as target:
                json.dump(astuple(snapshot), target)
                target.flush()
                os.fsync(target.fileno())
            temporary.replace(self._path)
            self._saved = snapshot
        except OSError as error:
            logger.warning("RECOVERY_POINT_WRITE_FAILED type=%s", type(error).__name__)
