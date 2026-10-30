"""Inicializa os recursos locais e abre a interface do StudyTimer."""

import logging

from app.config import AppPaths
from app.database.connection import initialize_database
from app.database.health import DatabaseHealthError, DatabaseVersionError
from app.database.repository import StudyRepository
from app.logging_config import configure_logging
from app.services.clock_service import ClockService, SystemClock
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from app.single_instance import AlreadyRunningError, SingleInstance
from app.ui.startup_dialog import show_startup_message


def main() -> None:
    """Protege a inicialização e informa falhas sem exibir dados privados."""
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        with SingleInstance(paths.data_dir / "instance.lock"):
            configure_logging(paths.log_file)
            run_application(paths)
    except AlreadyRunningError:
        show_startup_message("O StudyTimer já está aberto neste perfil do Windows.")
    except DatabaseHealthError:
        logging.getLogger("studytimer").error("STARTUP_DATABASE_INTEGRITY_FAILED")
        show_startup_message(
            "O banco não passou na verificação de integridade. "
            "Uma cópia de diagnóstico foi preservada junto aos dados. "
            "O original não foi reparado. Restaure um backup válido com o aplicativo fechado."
        )
    except DatabaseVersionError:
        logging.getLogger("studytimer").error("STARTUP_DATABASE_VERSION_UNSUPPORTED")
        show_startup_message("Este banco pertence a outra versão. Use uma versão compatível.")
    except Exception as error:
        # O texto da exceção pode conter caminhos e dados; registrar somente o tipo.
        logging.getLogger("studytimer").error("STARTUP_FAILED type=%s", type(error).__name__)
        show_startup_message(
            "Não foi possível abrir o StudyTimer. Verifique as permissões da pasta de dados "
            "e a instalação do programa. Consulte o log local para o código da falha."
        )


def run_application(paths: AppPaths) -> None:
    """Compõe as dependências e garante o fechamento da conexão ao sair."""
    # Importação tardia permite inspecionar a infraestrutura sem carregar widgets.
    from app.application import Application

    connection = initialize_database(paths.database)
    try:
        repository = StudyRepository(connection)
        clock = ClockService(SystemClock())
        timer = TimerService(repository, clock)
        timer.recover_pending()
        reports = ReportService(repository)
        application = Application(timer, reports)
        application.mainloop()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
