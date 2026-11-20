"""Descarga de factores externos. Todo es público y sin llaves.

- funding: tasa de financiamiento de los futuros perpetuos USDT-M de Binance (cada 8 horas),
  desde la API de futuros.
- metricas_futuros: interés abierto y proporciones de largos y cortos cada 5 minutos, de los
  archivos diarios de data.binance.vision. Esos archivos se publican al día siguiente, así que
  sirven para investigar, no para operar en vivo.
- miedo_codicia: índice diario de alternative.me.

Todo es incremental: cada corrida sigue desde lo último guardado.
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

from tradinglab.recolector.binance import ClienteBinance, ErrorBinance

log = logging.getLogger(__name__)

LIMITE_FUNDING = 1000
# Columnas del CSV de métricas, en el orden de la tabla metricas_futuros.
COLUMNAS_METRICAS = (
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
# Un archivo diario pesa unos KB; algo mucho mayor no es lo que esperamos.
MAXIMO_DESCOMPRIMIDO = 20 * 1024 * 1024


# --- Funding ----------------------------------------------------------------------------------


def descargar_funding(con: sqlite3.Connection, cliente: ClienteBinance, simbolo: str, inicio_ms: int) -> int:
    """Tasas de funding desde la última guardada (o desde inicio_ms). Devuelve cuántas se insertaron."""
    ultima = con.execute("SELECT MAX(ts) FROM funding WHERE simbolo = ?", (simbolo,)).fetchone()[0]
    desde = inicio_ms if ultima is None else ultima + 1
    insertadas = 0
    while True:
        filas = cliente.get("/fapi/v1/fundingRate", {"symbol": simbolo, "startTime": desde, "limit": LIMITE_FUNDING})
        if not filas:
            break
        datos = [(simbolo, int(f["fundingTime"]), float(f["fundingRate"])) for f in filas]
        with con:
            cursor = con.executemany("INSERT OR IGNORE INTO funding (simbolo, ts, tasa) VALUES (?, ?, ?)", datos)
        insertadas += cursor.rowcount
        desde = max(d[1] for d in datos) + 1
        if len(filas) < LIMITE_FUNDING:
            break
    return insertadas


# --- Métricas de futuros (data.binance.vision) -----------------------------------------------


def _numero(texto: str | None) -> float | None:
    if texto is None or texto.strip() == "":
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def leer_zip_metricas(contenido: bytes, simbolo: str) -> list[tuple]:
    """Filas de la tabla metricas_futuros a partir de un archivo diario (zip con un CSV)."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as archivo:
        nombre = archivo.namelist()[0]
        if archivo.getinfo(nombre).file_size > MAXIMO_DESCOMPRIMIDO:
            raise ValueError(f"Archivo de métricas sospechosamente grande: {nombre}")
        texto = archivo.read(nombre).decode("utf-8")
    filas = []
    for registro in csv.DictReader(io.StringIO(texto)):
        instante = datetime.fromisoformat(registro["create_time"]).replace(tzinfo=timezone.utc)
        valores = [_numero(registro.get(c)) for c in COLUMNAS_METRICAS]
        filas.append((simbolo, int(instante.timestamp() * 1000), *valores))
    return filas


class ArchivosBinance:
    """Descarga de archivos de data.binance.vision, con reintentos y una sesión por hilo."""

    def __init__(self, url_base: str, reintentos: int = 4, dormir: Callable[[float], None] = time.sleep) -> None:
        self.url_base = url_base.rstrip("/")
        self.reintentos = reintentos
        self._dormir = dormir
        self._local = threading.local()

    def _sesion(self) -> requests.Session:
        if not hasattr(self._local, "sesion"):
            self._local.sesion = requests.Session()
        return self._local.sesion

    @staticmethod
    def ruta_metricas(simbolo: str, dia: date) -> str:
        return f"/data/futures/um/daily/metrics/{simbolo}/{simbolo}-metrics-{dia:%Y-%m-%d}.zip"

    def bajar(self, ruta: str) -> bytes | None:
        """Contenido del archivo, o None si no existe (404)."""
        for intento in range(self.reintentos + 1):
            try:
                respuesta = self._sesion().get(self.url_base + ruta, timeout=30)
            except requests.RequestException as error:
                motivo = str(error)
            else:
                if respuesta.status_code == 200:
                    return respuesta.content
                if respuesta.status_code == 404:
                    return None
                motivo = f"HTTP {respuesta.status_code}"
            if intento < self.reintentos:
                self._dormir(min(2 ** (intento + 1), 30))
        raise ErrorBinance(f"No se pudo bajar {ruta}: {motivo}")


def primer_dia_disponible(
    existe: Callable[[date], bool], desde: date, hasta: date, tolerancia_huecos: int = 3
) -> date | None:
    """Búsqueda binaria del primer día con archivo.

    Una vez que empiezan los archivos, puede faltar algún día suelto. Para que un hueco no se
    confunda con "todavía no empiezan", un día sin archivo cuenta como empezado si alguno de los
    `tolerancia_huecos` días siguientes sí tiene. Puede devolver unos días antes del inicio real;
    esos días solo cuentan como faltantes.
    """
    if not existe(hasta):
        return None

    def empezado(dia: date) -> bool:
        return any(existe(dia + timedelta(days=k)) for k in range(tolerancia_huecos + 1) if dia + timedelta(days=k) <= hasta)

    bajo, alto = desde, hasta
    while bajo < alto:
        medio = bajo + (alto - bajo) // 2
        if empezado(medio):
            alto = medio
        else:
            bajo = medio + timedelta(days=1)
    return bajo


def descargar_metricas(
    con: sqlite3.Connection,
    archivos: ArchivosBinance,
    simbolo: str,
    inicio: date,
    hasta: date,
    hilos: int = 8,
    avisar: Callable[[str], None] = lambda texto: None,
) -> tuple[int, int]:
    """Métricas de cada día desde la última guardada hasta `hasta`. Devuelve (filas nuevas, días sin archivo)."""
    ultima = con.execute("SELECT MAX(ts) FROM metricas_futuros WHERE simbolo = ?", (simbolo,)).fetchone()[0]
    if ultima is not None:
        desde = datetime.fromtimestamp(ultima / 1000, tz=timezone.utc).date() + timedelta(days=1)
    else:
        primero = primer_dia_disponible(
            lambda d: archivos.bajar(archivos.ruta_metricas(simbolo, d)) is not None, inicio, hasta
        )
        if primero is None:
            avisar(f"{simbolo}: no hay archivos de métricas de futuros")
            return 0, 0
        desde = primero
        avisar(f"{simbolo}: las métricas de futuros empiezan el {primero}")
    if desde > hasta:
        return 0, 0

    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    insertadas = faltantes = 0
    pendientes: list[tuple] = []

    def guardar() -> int:
        if not pendientes:
            return 0
        with con:
            cursor = con.executemany(
                "INSERT OR IGNORE INTO metricas_futuros (simbolo, ts, interes_abierto, interes_abierto_usdt, "
                "ls_top_cuentas, ls_top_posiciones, ls_cuentas, taker_ls) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                pendientes,
            )
        pendientes.clear()
        return cursor.rowcount

    with ThreadPoolExecutor(max_workers=hilos) as grupo:
        contenidos = grupo.map(lambda d: archivos.bajar(archivos.ruta_metricas(simbolo, d)), dias)
        for n, (dia, contenido) in enumerate(zip(dias, contenidos), 1):
            if contenido is None:
                faltantes += 1
                continue
            pendientes.extend(leer_zip_metricas(contenido, simbolo))
            if n % 60 == 0:
                insertadas += guardar()
                avisar(f"{simbolo}: métricas hasta {dia} ({n:,} de {len(dias):,} días)")
    insertadas += guardar()
    return insertadas, faltantes


# --- Miedo y codicia -------------------------------------------------------------------------


def _obtener_json(url: str) -> Any:
    respuesta = requests.get(url, timeout=30)
    respuesta.raise_for_status()
    return respuesta.json()


def descargar_miedo_codicia(
    con: sqlite3.Connection, url: str, obtener_json: Callable[[str], Any] = _obtener_json
) -> int:
    """Todo el historial del índice (es una sola petición). Devuelve cuántos días hay."""
    datos = obtener_json(url)["data"]
    filas = [(int(d["timestamp"]) * 1000, int(d["value"]), str(d["value_classification"])) for d in datos]
    with con:
        # REPLACE: el valor del día en curso puede corregirse.
        con.executemany("INSERT OR REPLACE INTO miedo_codicia (ts, valor, clasificacion) VALUES (?, ?, ?)", filas)
    return len(filas)
