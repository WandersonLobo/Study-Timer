"""Amostra imutável dos relógios usados pelo cronômetro."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClockReading:
    """Contém amostras próximas dos relógios civil e monotônico."""

    wall_time_s: float
    monotonic_ns: int
