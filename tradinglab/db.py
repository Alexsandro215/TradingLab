"""Base de datos SQLite de TradingLab: conexión, esquema y acceso a las velas."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

# Se guarda en PRAGMA user_version. Súbelo (y migra) si cambia el esquema.
VERSION_ESQUEMA = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS velas (
    simbolo               TEXT    NOT NULL,  -- 'BTCUSDT', con el nombre de Binance
    intervalo             TEXT    NOT NULL,  -- '5m', '1h'
    ts                    INTEGER NOT NULL,  -- apertura de la vela, ms desde epoch, UTC
    apertura              REAL    NOT NULL,
    maximo                REAL    NOT NULL,
    minimo                REAL    NOT NULL,
    cierre                REAL    NOT NULL,
    volumen               REAL    NOT NULL,  -- en la moneda base (BTC, ETH, ZEC)
    volumen_cotizado      REAL    NOT NULL,  -- en la moneda de cotización (USDT)
    operaciones           INTEGER NOT NULL,  -- número de operaciones dentro de la vela
    compra_taker          REAL    NOT NULL,  -- volumen base comprado por agresores
    compra_taker_cotizado REAL    NOT NULL,  -- lo mismo, en USDT
    PRIMARY KEY (simbolo, intervalo, ts)
) WITHOUT ROWID;
"""

COLUMNAS_VELAS = (
    "simbolo",
    "intervalo",
    "ts",
    "apertura",
    "maximo",
    "minimo",
    "cierre",
    "volumen",
    "volumen_cotizado",
    "operaciones",
    "compra_taker",
    "compra_taker_cotizado",
)

_INSERTAR_VELA = (
    f"INSERT OR IGNORE INTO velas ({', '.join(COLUMNAS_VELAS)}) "
    f"VALUES ({', '.join('?' * len(COLUMNAS_VELAS))})"
)


def conectar(ruta: Path | str) -> sqlite3.Connection:
    """Abre (o crea) la base, activa el modo WAL y asegura que el esquema exista."""
    if str(ruta) != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    # WAL permite que el panel lea mientras el recolector escribe.
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    _asegurar_esquema(con)
    return con


def _asegurar_esquema(con: sqlite3.Connection) -> None:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION_ESQUEMA:
        raise RuntimeError(
            f"La base usa el esquema v{version}, más nuevo que el que conoce este código "
            f"(v{VERSION_ESQUEMA}). Actualiza el código antes de usarla."
        )
    con.executescript(ESQUEMA)
    con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
    con.commit()


def ultima_ts(con: sqlite3.Connection, simbolo: str, intervalo: str) -> int | None:
    """ts de la vela más reciente guardada de una serie, o None si la serie está vacía."""
    fila = con.execute(
        "SELECT MAX(ts) FROM velas WHERE simbolo = ? AND intervalo = ?",
        (simbolo, intervalo),
    ).fetchone()
    return fila[0]


def insertar_velas(con: sqlite3.Connection, filas: Sequence[tuple]) -> int:
    """Inserta velas en una sola transacción. Las que ya existen se ignoran.

    Devuelve cuántas filas se insertaron de verdad.
    """
    if not filas:
        return 0
    with con:
        cursor = con.executemany(_INSERTAR_VELA, filas)
    return cursor.rowcount
