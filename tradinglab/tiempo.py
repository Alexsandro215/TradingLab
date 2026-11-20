"""Utilidades de tiempo.

Todo el proyecto trabaja en UTC y guarda los instantes como enteros en milisegundos desde
epoch, igual que Binance. La conversión a texto legible se hace solo al mostrar.
"""

from __future__ import annotations

from datetime import datetime, timezone

MINUTO_MS = 60_000

# Intervalos de vela de Binance con duración fija (se omite "1M": los meses no miden lo mismo).
DURACION_MS: dict[str, int] = {
    "1m": MINUTO_MS,
    "3m": 3 * MINUTO_MS,
    "5m": 5 * MINUTO_MS,
    "15m": 15 * MINUTO_MS,
    "30m": 30 * MINUTO_MS,
    "1h": 60 * MINUTO_MS,
    "2h": 120 * MINUTO_MS,
    "4h": 240 * MINUTO_MS,
    "6h": 360 * MINUTO_MS,
    "8h": 480 * MINUTO_MS,
    "12h": 720 * MINUTO_MS,
    "1d": 1440 * MINUTO_MS,
    "3d": 3 * 1440 * MINUTO_MS,
    "1w": 7 * 1440 * MINUTO_MS,
}


def duracion_ms(intervalo: str) -> int:
    """Duración de una vela del intervalo dado, en milisegundos."""
    try:
        return DURACION_MS[intervalo]
    except KeyError:
        validos = ", ".join(DURACION_MS)
        raise ValueError(f"Intervalo no soportado: {intervalo!r}. Válidos: {validos}") from None


def fecha_a_ms(texto: str) -> int:
    """Convierte '2020-01-01' o '2020-01-01T12:00' (UTC si no trae zona) a ms desde epoch."""
    fecha = datetime.fromisoformat(texto)
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return int(fecha.timestamp() * 1000)


def ms_a_texto(ms: int) -> str:
    """Convierte ms desde epoch a texto legible en UTC, p. ej. '2020-01-01 00:00 UTC'."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
