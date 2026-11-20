"""Carga de velas desde SQLite para el backtest."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradinglab.tiempo import duracion_ms

COLUMNAS = ("ts", "apertura", "maximo", "minimo", "cierre", "volumen", "operaciones")


@dataclass
class Serie:
    """Velas de un par e intervalo, ordenadas por tiempo, con vistas numpy para el motor."""

    simbolo: str
    intervalo: str
    velas: pd.DataFrame  # columnas COLUMNAS, índice 0..n-1
    ts: np.ndarray = field(init=False, repr=False)
    apertura: np.ndarray = field(init=False, repr=False)
    cierre: np.ndarray = field(init=False, repr=False)
    operaciones: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.velas = self.velas.reset_index(drop=True)
        self.ts = self.velas["ts"].to_numpy(np.int64)
        self.apertura = self.velas["apertura"].to_numpy(np.float64)
        self.cierre = self.velas["cierre"].to_numpy(np.float64)
        self.operaciones = self.velas["operaciones"].to_numpy(np.int64)

    def __len__(self) -> int:
        return len(self.ts)

    @property
    def fin_ms(self) -> int:
        """Instante en que cierra la última vela (exclusivo)."""
        return int(self.ts[-1]) + duracion_ms(self.intervalo)

    def indice(self, ts_ms: int) -> int:
        """Primera vela con ts >= ts_ms."""
        return int(np.searchsorted(self.ts, ts_ms, side="left"))

    def rango(self, desde_ms: int | None, hasta_ms: int | None) -> tuple[int, int]:
        """Índices [inicio, fin) de las velas con desde_ms <= ts < hasta_ms."""
        inicio = 0 if desde_ms is None else self.indice(desde_ms)
        fin = len(self) if hasta_ms is None else self.indice(hasta_ms)
        return inicio, fin


def cargar_serie(con: sqlite3.Connection, simbolo: str, intervalo: str) -> Serie:
    """Carga toda la serie. Las estrategias calculan sobre todo el historial (sus indicadores
    solo miran hacia atrás) y el motor simula solo la ventana pedida."""
    cursor = con.execute(
        f"SELECT {', '.join(COLUMNAS)} FROM velas WHERE simbolo = ? AND intervalo = ? ORDER BY ts",
        (simbolo, intervalo),
    )
    velas = pd.DataFrame(cursor.fetchall(), columns=list(COLUMNAS))
    if velas.empty:
        raise ValueError(
            f"No hay velas de {simbolo} {intervalo}. Descárgalas con: "
            f"python -m tradinglab descargar --simbolo {simbolo} --intervalo {intervalo}"
        )
    velas = velas.astype({"ts": "int64", "operaciones": "int64"})
    return Serie(simbolo, intervalo, velas)
