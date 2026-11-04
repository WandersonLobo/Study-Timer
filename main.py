"""Inicializa os recursos locais e abre a interface do StudyTimer."""

import logging

from app.config import AppPaths
from app.database.connection import initialize_database
from app.database.health import DatabaseHealthError, DatabaseVersionError
from app.database.repository import StudyRepository
from app.logging_config import configure_logging, prepare_windowed_streams
from app.services.clock_service import ClockService, SystemClock
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from app.single_instance import AlreadyRunningError, SingleInstance
from app.ui.startup_dialog import show_startup_message


def main() -> None:
    """Protege a inicialização e informa falhas sem exibir dados privados."""
    try:
        prepare_windowed_streams()
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
        # Somente tipo e localização lógica; nunca texto da exceção ou caminhos.
        frame = error.__traceback__
        while frame is not None and frame.tb_next is not None:
            frame = frame.tb_next
        logging.getLogger("studytimer").error(
            "STARTUP_FAILED type=%s module=%s function=%s line=%s",
            type(error).__name__,
            str(frame.tb_frame.f_globals.get("__name__", "unknown")) if frame else "unknown",
            frame.tb_frame.f_code.co_name if frame else "unknown",
            frame.tb_lineno if frame else 0,
        )
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
        logging.getLogger("studytimer").info("APPLICATION_READY")
        application.mainloop()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
