"""Conexión en vivo al websocket público de Binance para la operación en papel.

Antes de conectarse (y después de cada desconexión) rellena con la API REST las velas que
falten, para que la señal siempre se calcule con la historia completa.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from tradinglab.papel.operador import Operador
from tradinglab.recolector.binance import ClienteBinance
from tradinglab.recolector.descarga import descargar_serie
from tradinglab.tiempo import duracion_ms

log = logging.getLogger(__name__)

# El primero es el oficial; el segundo, el de solo datos de mercado (respaldo).
URLS_WS = ("wss://stream.binance.com:9443/ws", "wss://data-stream.binance.vision/ws")


def rellenar(con: sqlite3.Connection, cliente: ClienteBinance, operador: Operador) -> None:
    """Descarga por REST las velas cerradas que falten y recalcula la señal."""
    s = operador.sesion
    inicio = int(time.time() * 1000) - int(operador.historia * 1.1) * duracion_ms(s.intervalo)
    r = descargar_serie(con, cliente, s.simbolo, s.intervalo, inicio)
    if r.insertadas:
        log.info("%s %s: %s velas rellenadas por REST", s.simbolo, s.intervalo, f"{r.insertadas:,}")
    operador.recalcular()


async def operar(
    con: sqlite3.Connection,
    cliente: ClienteBinance,
    operador: Operador,
    urls: tuple[str, ...] = URLS_WS,
    minutos: float | None = None,
) -> None:
    """Escucha las velas en vivo hasta que pasen `minutos` (o para siempre)."""
    s = operador.sesion
    flujo = f"{s.simbolo.lower()}@kline_{s.intervalo}"
    fin = time.monotonic() + minutos * 60 if minutos else None
    espera = 1.0
    indice = 0
    while fin is None or time.monotonic() < fin:
        # Bloquea unos segundos, pero mientras no hay conexión no llegan mensajes que atender.
        rellenar(con, cliente, operador)
        url = f"{urls[indice % len(urls)]}/{flujo}"
        try:
            async with connect(url, open_timeout=15, ping_interval=20, ping_timeout=20) as ws:
                log.info("Conectado a %s", url)
                operador.al_conectar()
                espera = 1.0
                while True:
                    restante = None if fin is None else fin - time.monotonic()
                    if restante is not None and restante <= 0:
                        return
                    try:
                        mensaje = await asyncio.wait_for(ws.recv(), timeout=restante)
                    except asyncio.TimeoutError:
                        return
                    datos = json.loads(mensaje)
                    if datos.get("e") == "kline":
                        operador.procesar_kline(datos["k"])
        except (WebSocketException, OSError, asyncio.TimeoutError) as error:
            log.warning("Se perdió la conexión (%s). Reintento en %.0f s", error, espera)
            indice += 1  # alterna con la URL de respaldo
            await asyncio.sleep(espera)
            espera = min(espera * 2, 60.0)
