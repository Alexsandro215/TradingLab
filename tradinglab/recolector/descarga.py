"""Descarga incremental de velas de Binance hacia SQLite.

Cada serie (par + intervalo) reanuda desde la última vela guardada. Solo se guardan velas
cerradas, en lotes con su propia transacción: si la descarga se corta, se pierde como mucho
el lote en curso. La llave primaria de la tabla impide duplicados.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from tradinglab import db
from tradinglab.tiempo import duracion_ms, ms_a_texto

log = logging.getLogger(__name__)

# Cada cuántos lotes se informa el avance.
AVISO_CADA_LOTES = 50


class FuenteVelas(Protocol):
    """Lo que la descarga necesita de Binance (permite usar una fuente simulada en pruebas)."""

    def hora_servidor(self) -> int: ...

    def velas(self, simbolo: str, intervalo: str, inicio_ms: int) -> list[list[Any]]: ...


@dataclass
class ResultadoDescarga:
    simbolo: str
    intervalo: str
    desde_ts: int  # primera vela que se pidió
    ultima_ts: int | None  # vela más reciente guardada al terminar
    insertadas: int = 0
    lotes: int = 0


def kline_a_fila(simbolo: str, intervalo: str, kline: Sequence[Any]) -> tuple:
    """Convierte una vela de Binance (lista de 12 campos) en una fila de la tabla velas.

    Campos de Binance: 0 apertura (ms), 1 open, 2 high, 3 low, 4 close, 5 volumen base,
    6 cierre (ms), 7 volumen cotizado, 8 número de operaciones, 9 compra taker base,
    10 compra taker cotizado, 11 sin uso.
    """
    return (
        simbolo,
        intervalo,
        int(kline[0]),
        float(kline[1]),
        float(kline[2]),
        float(kline[3]),
        float(kline[4]),
        float(kline[5]),
        float(kline[7]),
        int(kline[8]),
        float(kline[9]),
        float(kline[10]),
    )


def descargar_serie(
    con: sqlite3.Connection,
    fuente: FuenteVelas,
    simbolo: str,
    intervalo: str,
    inicio_ms: int,
) -> ResultadoDescarga:
    """Descarga las velas cerradas que falten de una serie, desde la última guardada."""
    duracion = duracion_ms(intervalo)
    ultima = db.ultima_ts(con, simbolo, intervalo)
    desde = inicio_ms if ultima is None else ultima + duracion
    ahora = fuente.hora_servidor()
    resultado = ResultadoDescarga(simbolo, intervalo, desde_ts=desde, ultima_ts=ultima)

    # Mientras pueda existir al menos una vela cerrada que no tenemos.
    while desde + duracion <= ahora:
        lote = fuente.velas(simbolo, intervalo, desde)
        resultado.lotes += 1
        cerradas = [k for k in lote if int(k[0]) + duracion <= ahora]
        if not cerradas:
            break

        filas = [kline_a_fila(simbolo, intervalo, k) for k in cerradas]
        resultado.insertadas += db.insertar_velas(con, filas)
        resultado.ultima_ts = max(fila[2] for fila in filas)

        siguiente = resultado.ultima_ts + duracion
        if siguiente <= desde:
            raise RuntimeError(f"{simbolo} {intervalo}: Binance devolvió velas que no avanzan")
        desde = siguiente

        if resultado.lotes % AVISO_CADA_LOTES == 0:
            log.info(
                "%s %s: guardado hasta %s (%s velas nuevas)",
                simbolo,
                intervalo,
                ms_a_texto(resultado.ultima_ts),
                f"{resultado.insertadas:,}",
            )

    return resultado
