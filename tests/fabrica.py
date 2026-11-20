"""Datos simulados para las pruebas: velas con el formato de Binance y una fuente falsa."""

from __future__ import annotations

from typing import Any

T0 = 1_577_836_800_000  # 2020-01-01 00:00 UTC
CINCO_MIN = 300_000
UNA_HORA = 3_600_000


def kline(ts: int, duracion: int, precio: float = 100.0, volumen: float = 2.0) -> list[Any]:
    """Una vela con los 12 campos de Binance (precios como texto, igual que la API)."""
    return [
        ts,
        f"{precio:.8f}",
        f"{precio * 1.01:.8f}",
        f"{precio * 0.99:.8f}",
        f"{precio * 1.005:.8f}",
        f"{volumen:.8f}",
        ts + duracion - 1,
        f"{volumen * precio:.8f}",
        10,
        f"{volumen / 2:.8f}",
        f"{volumen * precio / 2:.8f}",
        "0",
    ]


def kline_sin_operaciones(ts: int, duracion: int, cierre_anterior: str) -> list[Any]:
    """Vela sin operaciones: Binance la llena con el cierre de la vela anterior."""
    p = cierre_anterior
    return [ts, p, p, p, p, "0.00000000", ts + duracion - 1, "0.00000000", 0, "0.00000000", "0.00000000", "0"]


def serie(inicio: int, cantidad: int, duracion: int, saltar: set[int] | frozenset[int] = frozenset()) -> list[list[Any]]:
    """`cantidad` velas consecutivas con precios distintos; omite los índices de `saltar`."""
    return [
        kline(inicio + i * duracion, duracion, precio=100.0 + i, volumen=1.0 + i % 7)
        for i in range(cantidad)
        if i not in saltar
    ]


def agregar(finas: list[list[Any]], duracion_gruesa: int) -> list[list[Any]]:
    """Junta velas finas en velas gruesas, como lo hace Binance.

    Los precios salen solo de las velas con operaciones (si ninguna tiene, de todas).
    """
    bloques: dict[int, list[list[Any]]] = {}
    for k in finas:
        bloques.setdefault(k[0] // duracion_gruesa * duracion_gruesa, []).append(k)
    gruesas = []
    for ts, grupo in sorted(bloques.items()):
        volumen = sum(float(k[5]) for k in grupo)
        con_operaciones = [k for k in grupo if k[8] > 0] or grupo
        gruesas.append([
            ts,
            con_operaciones[0][1],
            f"{max(float(k[2]) for k in con_operaciones):.8f}",
            f"{min(float(k[3]) for k in con_operaciones):.8f}",
            con_operaciones[-1][4],
            f"{volumen:.8f}",
            ts + duracion_gruesa - 1,
            f"{sum(float(k[7]) for k in grupo):.8f}",
            sum(k[8] for k in grupo),
            f"{sum(float(k[9]) for k in grupo):.8f}",
            f"{sum(float(k[10]) for k in grupo):.8f}",
            "0",
        ])
    return gruesas


class FuenteFalsa:
    """Imita a ClienteBinance: devuelve hasta `limite` velas desde `inicio_ms`."""

    def __init__(self, klines: list[list[Any]], ahora: int, limite: int = 1000) -> None:
        self.klines = sorted(klines, key=lambda k: k[0])
        self.ahora = ahora
        self.limite = limite
        self.pedidos: list[int] = []

    def hora_servidor(self) -> int:
        return self.ahora

    def velas(self, simbolo: str, intervalo: str, inicio_ms: int) -> list[list[Any]]:
        self.pedidos.append(inicio_ms)
        return [k for k in self.klines if k[0] >= inicio_ms][: self.limite]


def serie_backtest(aperturas, cierres, operaciones=None, simbolo="BTCUSDT", intervalo="1h", inicio=T0):
    """Una Serie del backtest con velas de 1h a partir de listas de precios."""
    import pandas as pd

    from tradinglab.backtest.datos import Serie

    n = len(aperturas)
    velas = pd.DataFrame({
        "ts": [inicio + i * UNA_HORA for i in range(n)],
        "apertura": [float(x) for x in aperturas],
        "maximo": [max(a, c) * 1.01 for a, c in zip(aperturas, cierres)],
        "minimo": [min(a, c) * 0.99 for a, c in zip(aperturas, cierres)],
        "cierre": [float(x) for x in cierres],
        "volumen": [1.0] * n,
        "operaciones": operaciones if operaciones is not None else [10] * n,
    })
    return Serie(simbolo, intervalo, velas)


def caminata(n, semilla=0, inicio=T0):
    """Serie con precios de caminata aleatoria (para pruebas generales)."""
    import numpy as np

    rng = np.random.default_rng(semilla)
    cierres = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    aperturas = np.concatenate([[100.0], cierres[:-1]])
    return serie_backtest(list(aperturas), list(cierres), inicio=inicio)
