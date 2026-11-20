"""Base de datos SQLite de TradingLab: conexión, esquema y acceso a las velas."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

# Se guarda en PRAGMA user_version. Súbelo (y migra) si cambia el esquema.
# v1: velas. v2: estudios y corridas (fase 3), operación en papel (fase 5).
# Hasta ahora los cambios solo agregan tablas, así que ESQUEMA (todo con IF NOT EXISTS) migra solo.
VERSION_ESQUEMA = 2

ESQUEMA = """
-- Fase 1: velas de Binance.
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

-- Fase 3: cada estudio (backtest guardado, barrido o walk-forward) y sus corridas.
CREATE TABLE IF NOT EXISTS estudios (
    id              INTEGER PRIMARY KEY,
    creado_ms       INTEGER NOT NULL,
    tipo            TEXT    NOT NULL,   -- 'backtest', 'barrido' o 'walk_forward'
    descripcion     TEXT    NOT NULL,
    configuracion   TEXT    NOT NULL,   -- JSON: estrategias, rejillas, ventanas, costos, capital
    combinaciones   INTEGER NOT NULL,   -- simulaciones corridas en total (para medir el sobreajuste)
    commit_git      TEXT,               -- versión del código; termina en '+cambios' si había cambios sin commit
    datos_hasta_ms  INTEGER,            -- última vela usada
    resumen         TEXT                -- JSON con el resultado agregado
);

CREATE TABLE IF NOT EXISTS corridas (
    id               INTEGER PRIMARY KEY,
    estudio_id       INTEGER NOT NULL REFERENCES estudios(id) ON DELETE CASCADE,
    simbolo          TEXT    NOT NULL,
    intervalo        TEXT    NOT NULL,
    estrategia       TEXT    NOT NULL,
    parametros       TEXT    NOT NULL,  -- JSON
    ventana          TEXT    NOT NULL,  -- nombre legible: '2021', 'completa', 'pliegue 3'
    muestra          TEXT    NOT NULL,  -- 'completa', 'entrenamiento' o 'prueba'
    desde_ms         INTEGER NOT NULL,
    hasta_ms         INTEGER NOT NULL,  -- exclusivo
    rendimiento      REAL    NOT NULL,  -- fracción: 0.1 = +10%
    drawdown_maximo  REAL    NOT NULL,  -- fracción negativa: -0.3 = -30%
    operaciones      INTEGER NOT NULL,
    comisiones       REAL    NOT NULL,  -- en USDT
    ganadoras        REAL,              -- fracción de operaciones ganadoras; NULL si no hubo
    exposicion       REAL    NOT NULL,  -- fracción del tiempo con posición abierta
    bh_rendimiento   REAL    NOT NULL,  -- comprar y mantener, misma ventana y mismos costos
    bh_drawdown      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS corridas_por_estudio ON corridas (estudio_id);

-- Fase 5: operación en papel (sin dinero real).
CREATE TABLE IF NOT EXISTS papel_sesiones (
    nombre          TEXT    PRIMARY KEY,
    creada_ms       INTEGER NOT NULL,
    simbolo         TEXT    NOT NULL,
    intervalo       TEXT    NOT NULL,
    estrategia      TEXT    NOT NULL,
    parametros      TEXT    NOT NULL,  -- JSON
    capital_inicial REAL    NOT NULL,
    fraccion        REAL    NOT NULL,
    comision        REAL    NOT NULL,
    deslizamiento   REAL    NOT NULL,
    efectivo        REAL    NOT NULL,  -- USDT
    cantidad        REAL    NOT NULL,  -- moneda base en posición
    objetivo        INTEGER NOT NULL DEFAULT 0,  -- última señal: 1 = dentro, 0 = fuera
    precio_entrada  REAL,              -- costo por unidad de la posición abierta (con costos)
    ultimo_precio   REAL,
    actualizada_ms  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS papel_operaciones (
    id              INTEGER PRIMARY KEY,
    sesion          TEXT    NOT NULL REFERENCES papel_sesiones(nombre) ON DELETE CASCADE,
    ts              INTEGER NOT NULL,  -- apertura de la vela en la que se ejecutó
    lado            TEXT    NOT NULL,  -- 'compra' o 'venta'
    precio          REAL    NOT NULL,  -- precio de ejecución, ya con deslizamiento
    cantidad        REAL    NOT NULL,
    comision        REAL    NOT NULL,
    efectivo        REAL    NOT NULL   -- efectivo después de la operación
);

CREATE TABLE IF NOT EXISTS papel_capital (
    sesion          TEXT    NOT NULL REFERENCES papel_sesiones(nombre) ON DELETE CASCADE,
    ts              INTEGER NOT NULL,  -- apertura de la vela cerrada
    capital         REAL    NOT NULL,  -- efectivo + posición valuada al cierre
    PRIMARY KEY (sesion, ts)
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
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    _asegurar_esquema(con)
    return con


def conectar_lectura(ruta: Path | str) -> sqlite3.Connection:
    """Conexión de solo lectura (para el panel): no toca el esquema ni bloquea a quien escribe."""
    uri = Path(ruta).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.execute("PRAGMA busy_timeout = 10000")
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
