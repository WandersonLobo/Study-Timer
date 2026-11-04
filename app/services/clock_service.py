"""Relógio injetável com duração monotônica e pausa conservadora de ticks."""

import logging
import math
import time
from typing import Protocol

from app.config import MAX_CLOCK_DRIFT_S, MAX_TICK_GAP_S
from app.models import ClockReading, ClockSnapshot, PauseReason

NANOSECONDS_PER_SECOND = 1_000_000_000
logger = logging.getLogger("studytimer.clock")


class ClockSource(Protocol):
    """Permite substituir os relógios reais por amostras controladas nos testes."""

    def read(self) -> ClockReading:
        """Captura os relógios civil e monotônico em sequência próxima."""
        ...


class SystemClock:
    """Captura amostras reais sem decidir se o tick deve ser contabilizado."""

    def read(self) -> ClockReading:
        """Retorna a âncora civil e os nanossegundos monotônicos atuais."""
        return ClockReading(wall_time_s=time.time(), monotonic_ns=time.monotonic_ns())


class ClockService:
    """Valida um intervalo por vez sem conhecer SQLite, widgets ou agendamento.

    Somente tick() aceita tempo novo. Snapshots são imutáveis e compartilhados
    entre consumidores. Uma pausa conserva o último snapshot até outro início
    explícito ou reset; a persistência da sessão pertence ao TimerService.
    """

    def __init__(self, source: ClockSource) -> None:
        self._source = source
        self._start_mono_ns: int | None = None
        self._last_reading: ClockReading | None = None
        self._snapshot: ClockSnapshot | None = None
        self._is_running = False
        self._pause_reason: PauseReason | None = None

    @property
    def is_running(self) -> bool:
        """Indica se o próximo tick pode aceitar tempo para o intervalo."""
        return self._is_running

    @property
    def pause_reason(self) -> PauseReason | None:
        """Informa o motivo da primeira pausa desde o último início."""
        return self._pause_reason

    def capture_anchor(self) -> ClockReading:
        """Captura uma âncora sem aceitar ticks nem alterar o intervalo atual.

        Returns:
            Par de relógios que pode ser reutilizado na criação transacional
            do intervalo e em start_interval(), evitando duas âncoras distintas.

        Raises:
            ValueError: Se a fonte produzir um horário civil não finito.
        """
        reading = self._source.read()
        if not math.isfinite(reading.wall_time_s):
            raise ValueError("A amostra do relógio civil deve ser finita.")
        return reading

    def start_interval(self, interval_id: int, anchor: ClockReading | None = None) -> ClockSnapshot:
        """Inicia um novo intervalo com duração zero e uma única âncora UTC.

        Args:
            interval_id: Identificador positivo do intervalo no repositório.
            anchor: Amostra previamente capturada; se omitida, captura agora.
                Sua parte civil inteira deve ser o started_at gravado no banco.

        Returns:
            Snapshot inicial, sem contabilizar o intervalo anterior ou a pausa.

        Raises:
            RuntimeError: Se já existir um intervalo em execução.
            ValueError: Se o identificador ou a âncora civil forem inválidos.
        """
        if self._is_running:
            raise RuntimeError("Pause o intervalo atual antes de iniciar outro.")
        if interval_id <= 0:
            raise ValueError("O identificador do intervalo deve ser positivo.")
        reading = self.capture_anchor() if anchor is None else anchor
        if not math.isfinite(reading.wall_time_s):
            raise ValueError("A amostra do relógio civil deve ser finita.")
        started_at = int(reading.wall_time_s)
        snapshot = ClockSnapshot(
            interval_id=interval_id,
            started_at=started_at,
            elapsed_s=0,
            valid_until_utc_s=started_at,
        )
        self._start_mono_ns = reading.monotonic_ns
        self._last_reading = reading
        self._snapshot = snapshot
        self._pause_reason = None
        self._is_running = True
        return snapshot

    def tick(self) -> ClockSnapshot | None:
        """Aceita uma leitura confiável ou congela o último tick sem creditar saltos.

        Returns:
            Snapshot validado, o último snapshot congelado ou None antes do início.
            Lacuna acima de 5 s, regressão monotônica ou divergência civil acima
            de 5 s pausam o relógio. Consulte is_running e pause_reason.

        Raises:
            Exception: Propaga falhas da fonte após congelar a contagem; logs
                registram somente o tipo da falha, sem seu texto potencialmente privado.
        """
        if not self._is_running:
            return self._snapshot
        last_reading = self._last_reading
        snapshot = self._snapshot
        start_mono_ns = self._start_mono_ns
        assert last_reading is not None and snapshot is not None and start_mono_ns is not None
        try:
            reading = self.capture_anchor()
        except Exception as error:
            self.pause(PauseReason.CLOCK_CHANGE)
            logger.error("CLOCK_SOURCE_FAILED type=%s", type(error).__name__)
            raise
        delta_ns = reading.monotonic_ns - last_reading.monotonic_ns
        if delta_ns < 0:
            return self.pause(PauseReason.CLOCK_CHANGE)
        if delta_ns > MAX_TICK_GAP_S * NANOSECONDS_PER_SECOND:
            return self.pause(PauseReason.TICK_GAP)
        wall_delta_s = reading.wall_time_s - last_reading.wall_time_s
        if abs(wall_delta_s - delta_ns / NANOSECONDS_PER_SECOND) > MAX_CLOCK_DRIFT_S:
            return self.pause(PauseReason.CLOCK_CHANGE)

        elapsed_s = max(0, (reading.monotonic_ns - start_mono_ns) // NANOSECONDS_PER_SECOND)
        self._snapshot = ClockSnapshot(
            interval_id=snapshot.interval_id,
            started_at=snapshot.started_at,
            elapsed_s=elapsed_s,
            valid_until_utc_s=snapshot.started_at + elapsed_s,
        )
        self._last_reading = reading
        return self._snapshot

    def pause(self, reason: PauseReason = PauseReason.USER) -> ClockSnapshot | None:
        """Congela o último tick válido sem ler nem contabilizar o relógio atual.

        Args:
            reason: Motivo da pausa, preservado em chamadas posteriores.

        Returns:
            Snapshot a persistir pelo chamador, ou None se nenhum intervalo iniciou.
        """
        if self._is_running:
            self._is_running = False
            self._pause_reason = reason
            level = (
                logging.WARNING
                if reason in (PauseReason.TICK_GAP, PauseReason.CLOCK_CHANGE)
                else logging.INFO
            )
            logger.log(level, "CLOCK_PAUSED reason=%s", reason.value)
        return self._snapshot

    def get_snapshot(self) -> ClockSnapshot | None:
        """Retorna o último snapshot sem ler relógios ou aceitar tempo novo."""
        return self._snapshot

    def reset(self) -> None:
        """Descarta o intervalo parado após o chamador concluir sua persistência.

        Raises:
            RuntimeError: Se o intervalo ainda estiver em execução.
        """
        if self._is_running:
            raise RuntimeError("Pause o intervalo antes de limpar o relógio.")
        self._start_mono_ns = None
        self._last_reading = None
        self._snapshot = None
        self._pause_reason = None
