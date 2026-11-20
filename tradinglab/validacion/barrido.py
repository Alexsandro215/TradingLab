"""Corridas masivas: todas las combinaciones de parámetros en muchas ventanas.

Un barrido es TODO dentro de muestra: sirve para ver el panorama (¿cuántas combinaciones le
ganan a las referencias, en qué años?), no como evidencia. El mejor resultado de muchos
intentos está inflado por suerte; la evidencia sale del walk-forward.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from typing import Any, Callable

from tradinglab.backtest.datos import cargar_serie
from tradinglab.backtest.estrategias import obtener
from tradinglab.backtest.motor import comprar_y_mantener, simular
from tradinglab.config import ConfigCostos
from tradinglab.validacion.registro import fila_corrida
from tradinglab.validacion.ventanas import ventanas_estandar


@dataclass
class ResultadoBarrido:
    corridas: list[dict[str, Any]]
    datos_hasta_ms: int
    resumen: dict[str, Any]


def correr_barrido(
    con: sqlite3.Connection,
    simbolos: list[str],
    intervalos: list[str],
    estrategias: list[str],
    tipos_ventana: list[str],
    costos: ConfigCostos,
    capital: float,
    fraccion: float = 1.0,
    avisar: Callable[[str], None] = lambda texto: None,
) -> ResultadoBarrido:
    corridas: list[dict[str, Any]] = []
    datos_hasta = 0
    for simbolo in simbolos:
        costos_par = costos.para(simbolo)
        for intervalo in intervalos:
            serie = cargar_serie(con, simbolo, intervalo)
            datos_hasta = max(datos_hasta, serie.fin_ms)
            rangos = []
            for v in ventanas_estandar(tipos_ventana, int(serie.ts[0]), serie.fin_ms):
                inicio, fin = serie.rango(v.desde_ms, v.hasta_ms)
                if fin - inicio >= 2:
                    bh = comprar_y_mantener(serie, inicio, fin, costos_par, capital).metricas
                    rangos.append((v, inicio, fin, bh))
            for nombre in estrategias:
                estrategia = obtener(nombre)
                rejilla = estrategia.rejilla()
                for parametros in rejilla:
                    objetivo = estrategia.objetivo(serie.velas, parametros)
                    for v, inicio, fin, bh in rangos:
                        m = simular(serie, objetivo, inicio, fin, costos_par, capital, fraccion).metricas
                        corridas.append(fila_corrida(
                            simbolo, intervalo, nombre, parametros, v.nombre, "completa", v.desde_ms, v.hasta_ms, m, bh,
                        ))
                avisar(f"{simbolo} {intervalo} {nombre}: {len(rejilla)} combinaciones x {len(rangos)} ventanas")
    return ResultadoBarrido(corridas, datos_hasta, resumir_barrido(corridas))


def _cuenta(corridas: list[dict[str, Any]]) -> dict[str, Any]:
    rendimientos = [c["rendimiento"] for c in corridas]
    mejor = max(corridas, key=lambda c: c["rendimiento"])
    return {
        "corridas": len(corridas),
        "ganan_a_no_operar": sum(c["rendimiento"] > 0 for c in corridas),
        "ganan_a_comprar_y_mantener": sum(c["rendimiento"] > c["bh_rendimiento"] for c in corridas),
        "ganan_a_ambas": sum(c["rendimiento"] > max(0.0, c["bh_rendimiento"]) for c in corridas),
        "mediana": statistics.median(rendimientos),
        "mejor": {k: mejor[k] for k in ("estrategia", "parametros", "rendimiento", "drawdown_maximo", "operaciones")},
    }


def resumir_barrido(corridas: list[dict[str, Any]]) -> dict[str, Any]:
    """Conteos de cuántas corridas le ganan a cada referencia: total, por ventana y por estrategia."""
    if not corridas:
        return {"total": None, "por_ventana": [], "por_estrategia": []}

    def agrupar(claves: tuple[str, ...]) -> dict[tuple, list[dict[str, Any]]]:
        grupos: dict[tuple, list[dict[str, Any]]] = {}
        for c in corridas:
            grupos.setdefault(tuple(c[k] for k in claves), []).append(c)
        return grupos

    por_ventana = []
    for (simbolo, intervalo, ventana), grupo in agrupar(("simbolo", "intervalo", "ventana")).items():
        fila = {"simbolo": simbolo, "intervalo": intervalo, "ventana": ventana,
                "bh_rendimiento": grupo[0]["bh_rendimiento"], "bh_drawdown": grupo[0]["bh_drawdown"]}
        fila.update(_cuenta(grupo))
        por_ventana.append(fila)

    por_estrategia = []
    for (estrategia,), grupo in agrupar(("estrategia",)).items():
        fila = {"estrategia": estrategia}
        fila.update(_cuenta(grupo))
        por_estrategia.append(fila)

    return {"total": _cuenta(corridas), "por_ventana": por_ventana, "por_estrategia": por_estrategia}
