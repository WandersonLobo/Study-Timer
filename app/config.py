"""Configurações e caminhos dos dados locais, separados do executável."""

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "StudyTimer"
WINDOW_SIZE = "1180x740"
MIN_WINDOW_SIZE = (900, 600)
TICK_INTERVAL_MS = 250
HEARTBEAT_INTERVAL_S = 5
MAX_TICK_GAP_S = 5
MAX_CLOCK_DRIFT_S = 5
MAX_SESSION_NAME_LENGTH = 120
MAX_STUDY_TYPE_NAME_LENGTH = 60
DEFAULT_SESSION_NAME = "Estudo livre"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Agrupa os caminhos persistentes do perfil Windows atual."""

    data_dir: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        """Resolve LOCALAPPDATA sem recorrer à pasta do executável.

        Raises:
            RuntimeError: Se o perfil não informar LOCALAPPDATA.
        """
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA não definido. Execute no perfil Windows do usuário.")
        return cls(Path(local_app_data) / APP_NAME)

    @property
    def database(self) -> Path:
        """Retorna o caminho do banco de estudos."""
        return self.data_dir / "estudos.db"

    @property
    def log_file(self) -> Path:
        """Retorna o caminho do log rotativo."""
        return self.data_dir / "logs" / "studytimer.log"

    def ensure_directories(self) -> None:
        """Cria os diretórios de dados e logs do perfil atual."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
