"""Factores alineados con las velas, sin ver el futuro.

Para cada vela, cada factor toma el último valor que ya se conocía al CIERRE de esa vela:
- funding: la última tasa cobrada (se conoce en el momento del cobro);
- métricas de futuros: el último registro de 5 minutos;
- miedo y codicia: el valor del día ANTERIOR. El de hoy se publica durante el día y no
  sabemos a qué hora; así se evita usarlo antes de tiempo.
Si el último valor es demasiado viejo (faltan datos), el factor queda vacío (NaN).
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from tradinglab.backtest.datos import Serie
from tradinglab.tiempo import duracion_ms

HORA_MS = 3_600_000
DIA_MS = 24 * HORA_MS

FACTORES: dict[str, str] = {
    "funding": "última tasa de funding de los futuros (cada 8 h)",
    "funding_3d": "promedio de las últimas 9 tasas de funding (3 días)",
    "oi_cambio_24h": "cambio del interés abierto de los futuros en 24 h",
    "ls_top": "largos/cortos de las cuentas grandes en futuros (por posición)",
    "taker_ls_fut": "volumen agresivo comprador/vendedor en futuros (últimos 5 min)",
    "miedo_codicia": "índice de miedo y codicia del día anterior (0 a 100)",
    "flujo_taker_24h": "compras agresivas / volumen en spot, últimas 24 h (0.5 = equilibrio)",
    "rendimiento_24h": "referencia: rendimiento de las últimas 24 h",
    "volatilidad_24h": "referencia: volatilidad de las últimas 24 h",
}
# Factores de referencia: salen del propio precio. Sirven para ver si un factor externo agrega
# algo más allá de lo que ya dice el precio.
REFERENCIAS = ("rendimiento_24h", "volatilidad_24h")


def _asof(claves: np.ndarray, tabla: pd.DataFrame, columnas: list[str], tolerancia: int) -> pd.DataFrame:
    """Para cada clave, el último registro de `tabla` con ts <= clave (y no más viejo que la tolerancia)."""
    izquierda = pd.DataFrame({"clave": claves.astype(np.int64)})
    if tabla.empty:
        return pd.DataFrame({c: np.full(len(claves), np.nan) for c in columnas})
    derecha = tabla[["ts", *columnas]].sort_values("ts").astype({"ts": "int64"})
    unida = pd.merge_asof(izquierda, derecha, left_on="clave", right_on="ts", direction="backward",
                          tolerance=tolerancia)
    return unida[columnas].reset_index(drop=True)


def tabla_factores(con: sqlite3.Connection, serie: Serie) -> pd.DataFrame:
    """Un DataFrame con una fila por vela de la serie y una columna por factor."""
    duracion = duracion_ms(serie.intervalo)
    cierre_ms = serie.ts + duracion  # todo lo que se conocía al cierre de la vela
    velas_24h = max(1, DIA_MS // duracion)
    salida = pd.DataFrame(index=range(len(serie)))

    funding = pd.DataFrame(
        con.execute("SELECT ts, tasa FROM funding WHERE simbolo = ? ORDER BY ts", (serie.simbolo,)).fetchall(),
        columns=["ts", "tasa"],
    )
    funding["funding_3d"] = funding["tasa"].rolling(9, min_periods=9).mean()
    f = _asof(cierre_ms, funding, ["tasa", "funding_3d"], tolerancia=9 * HORA_MS)
    salida["funding"] = f["tasa"]
    salida["funding_3d"] = f["funding_3d"]

    metricas = pd.DataFrame(
        con.execute(
            "SELECT ts, interes_abierto, ls_top_posiciones, taker_ls FROM metricas_futuros WHERE simbolo = ? ORDER BY ts",
            (serie.simbolo,),
        ).fetchall(),
        columns=["ts", "interes_abierto", "ls_top_posiciones", "taker_ls"],
    )
    tolerancia_5m = 30 * 60_000
    ahora = _asof(cierre_ms, metricas, ["interes_abierto", "ls_top_posiciones", "taker_ls"], tolerancia_5m)
    antes = _asof(cierre_ms - DIA_MS, metricas, ["interes_abierto"], tolerancia_5m)
    salida["oi_cambio_24h"] = ahora["interes_abierto"] / antes["interes_abierto"] - 1
    salida["ls_top"] = ahora["ls_top_posiciones"]
    salida["taker_ls_fut"] = ahora["taker_ls"]

    miedo = pd.DataFrame(con.execute("SELECT ts, valor FROM miedo_codicia ORDER BY ts").fetchall(), columns=["ts", "valor"])
    miedo["ts"] = miedo["ts"] + DIA_MS  # disponible desde el día siguiente
    salida["miedo_codicia"] = _asof(cierre_ms, miedo, ["valor"], tolerancia=3 * DIA_MS)["valor"]

    flujo = pd.DataFrame(
        con.execute(
            "SELECT compra_taker, volumen FROM velas WHERE simbolo = ? AND intervalo = ? ORDER BY ts",
            (serie.simbolo, serie.intervalo),
        ).fetchall(),
        columns=["compra_taker", "volumen"],
    )
    if len(flujo) == len(serie):
        compras = flujo["compra_taker"].rolling(velas_24h).sum()
        volumen = flujo["volumen"].rolling(velas_24h).sum()
        salida["flujo_taker_24h"] = (compras / volumen.where(volumen > 0)).to_numpy()
    else:  # la serie no viene completa de la base (p. ej. en pruebas)
        salida["flujo_taker_24h"] = np.nan

    cierre = pd.Series(serie.cierre)
    salida["rendimiento_24h"] = cierre / cierre.shift(velas_24h) - 1
    salida["volatilidad_24h"] = np.log(cierre).diff().rolling(velas_24h).std()
    return salida[list(FACTORES)]
