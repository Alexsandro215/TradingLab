"""Validación fuera de muestra (walk-forward).

En cada pliegue:
1. Se prueban todas las combinaciones de la rejilla en el periodo de entrenamiento.
2. Se elige la mejor según el criterio.
3. Esa combinación se corre en el periodo de prueba siguiente, que no vio.

Solo los periodos de prueba cuentan como evidencia. Se encadenan (el capital final de una
prueba es el inicial de la siguiente) y se comparan con no operar y con comprar y mantener en
todo el tramo fuera de muestra.

Indicadores de sobreajuste que se reportan:
- cuántas simulaciones se corrieron en total;
- el rendimiento mensual equivalente de la combinación elegida en entrenamiento contra el que
  luego logró en prueba (si en prueba cae mucho, lo de entrenamiento era suerte);
- cuántas veces cambió la combinación elegida entre pliegues (inestabilidad).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np

from tradinglab.backtest.costos import Costos
from tradinglab.backtest.datos import cargar_serie
from tradinglab.backtest.estrategias import obtener, texto_parametros
from tradinglab.backtest.motor import Metricas, comprar_y_mantener, simular
from tradinglab.validacion.registro import fila_corrida
from tradinglab.validacion.ventanas import DIA_MS, pliegues_walk_forward

CRITERIOS = ("rendimiento", "calmar")
DIAS_POR_MES = 30.4375


def puntaje(m: Metricas, criterio: str) -> tuple[bool, float]:
    """Clave para elegir la mejor combinación (mayor es mejor).

    - rendimiento: el mayor rendimiento neto.
    - calmar: rendimiento entre drawdown máximo (con piso de 5%). Las combinaciones con
      rendimiento positivo siempre van antes; entre las negativas, la que pierde menos.
    """
    if criterio == "rendimiento":
        return (True, m.rendimiento)
    if criterio == "calmar":
        if m.rendimiento > 0:
            return (True, m.rendimiento / max(-m.drawdown_maximo, 0.05))
        return (False, m.rendimiento)
    raise ValueError(f"Criterio desconocido: {criterio!r}. Hay: {', '.join(CRITERIOS)}")


def mensual(rendimiento: float, dias: float) -> float:
    """Rendimiento mensual equivalente de un rendimiento logrado en `dias`."""
    if rendimiento <= -1:
        return -1.0
    return (1 + rendimiento) ** (DIAS_POR_MES / dias) - 1


@dataclass
class ResultadoWalkForward:
    resumen: dict[str, Any]
    pliegues: list[dict[str, Any]]
    corridas: list[dict[str, Any]]
    ts: np.ndarray  # curva de capital encadenada fuera de muestra
    capital: np.ndarray
    capital_bh: np.ndarray


def correr_walk_forward(
    con: sqlite3.Connection,
    simbolo: str,
    intervalo: str,
    estrategia: str,
    meses_entrenamiento: int,
    meses_prueba: int,
    criterio: str,
    costos: Costos,
    capital: float,
    fraccion: float = 1.0,
    anclado: bool = False,
) -> ResultadoWalkForward:
    puntaje(Metricas(1, 1, 0, 0, 0, 0, 0, None, 0), criterio)  # valida el criterio
    e = obtener(estrategia)
    serie = cargar_serie(con, simbolo, intervalo, con_factores=bool(e.factores))
    rejilla = e.rejilla()
    objetivos = [e.objetivo(serie.velas, p) for p in rejilla]

    pliegues_def = pliegues_walk_forward(int(serie.ts[0]), serie.fin_ms, meses_entrenamiento, meses_prueba, anclado)
    if not pliegues_def:
        raise ValueError("No alcanzan los datos para un solo pliegue; reduce los meses de entrenamiento o de prueba")

    corridas: list[dict[str, Any]] = []
    pliegues: list[dict[str, Any]] = []
    tramos_ts, tramos_capital = [], []
    acumulado = capital
    comisiones = 0.0
    operaciones = ganadoras = 0
    anterior: str | None = None
    cambios = 0

    for entrenamiento, prueba in pliegues_def:
        i0, i1 = serie.rango(entrenamiento.desde_ms, entrenamiento.hasta_ms)
        j0, j1 = serie.rango(prueba.desde_ms, prueba.hasta_ms)
        if i1 - i0 < 2 or j1 - j0 < 2:
            continue
        bh_ent = comprar_y_mantener(serie, i0, i1, costos, capital).metricas
        evaluadas = []
        for parametros, objetivo in zip(rejilla, objetivos):
            m = simular(serie, objetivo, i0, i1, costos, capital, fraccion).metricas
            evaluadas.append((parametros, objetivo, m))
            corridas.append(fila_corrida(
                simbolo, intervalo, estrategia, parametros, entrenamiento.nombre, "entrenamiento",
                entrenamiento.desde_ms, entrenamiento.hasta_ms, m, bh_ent,
            ))
        # max() devuelve la primera en caso de empate: el orden de la rejilla decide.
        elegidos, objetivo, m_ent = max(evaluadas, key=lambda t: puntaje(t[2], criterio))

        r = simular(serie, objetivo, j0, j1, costos, capital, fraccion)
        bh = comprar_y_mantener(serie, j0, j1, costos, capital).metricas
        m = r.metricas
        corridas.append(fila_corrida(
            simbolo, intervalo, estrategia, elegidos, prueba.nombre, "prueba", prueba.desde_ms, prueba.hasta_ms, m, bh,
        ))

        # Encadenar: cada prueba arranca con el capital con que terminó la anterior.
        escala = acumulado / capital
        tramos_ts.append(r.ts)
        tramos_capital.append(r.capital * escala)
        comisiones += m.comisiones * escala
        operaciones += m.operaciones
        ganadoras += round((m.ganadoras or 0) * m.operaciones)
        acumulado = float(r.capital[-1] * escala)

        clave = texto_parametros(elegidos)
        cambios += anterior is not None and clave != anterior
        anterior = clave
        pliegues.append({
            "pliegue": prueba.nombre,
            "entrenamiento_desde_ms": entrenamiento.desde_ms,
            "prueba_desde_ms": prueba.desde_ms,
            "prueba_hasta_ms": prueba.hasta_ms,
            "parametros": elegidos,
            "rendimiento_entrenamiento": m_ent.rendimiento,
            "bh_entrenamiento": bh_ent.rendimiento,
            "mensual_entrenamiento": mensual(m_ent.rendimiento, entrenamiento.dias),
            "rendimiento_prueba": m.rendimiento,
            "drawdown_prueba": m.drawdown_maximo,
            "operaciones_prueba": m.operaciones,
            "bh_prueba": bh.rendimiento,
            "mensual_prueba": mensual(m.rendimiento, prueba.dias),
        })

    if not pliegues:
        raise ValueError("Ningún pliegue tuvo velas suficientes")

    ts = np.concatenate(tramos_ts)
    curva = np.concatenate(tramos_capital)
    drawdown = curva / np.maximum.accumulate(curva) - 1
    desde_oos, hasta_oos = pliegues[0]["prueba_desde_ms"], pliegues[-1]["prueba_hasta_ms"]
    k0, k1 = serie.rango(desde_oos, hasta_oos)
    bh_total = comprar_y_mantener(serie, k0, k1, costos, capital)
    # La curva del comprar y mantener alineada con la de la estrategia (mismas velas).
    capital_bh = bh_total.capital[np.searchsorted(bh_total.ts, ts)]

    rendimiento = acumulado / capital - 1
    dias_oos = (hasta_oos - desde_oos) / DIA_MS
    resumen = {
        "simbolo": simbolo,
        "intervalo": intervalo,
        "estrategia": estrategia,
        "criterio": criterio,
        "meses_entrenamiento": meses_entrenamiento,
        "meses_prueba": meses_prueba,
        "anclado": anclado,
        "pliegues": len(pliegues),
        "combinaciones_por_pliegue": len(rejilla),
        "simulaciones": len(corridas),
        "oos_desde_ms": desde_oos,
        "oos_hasta_ms": hasta_oos,
        "rendimiento": rendimiento,
        "drawdown_maximo": float(drawdown.min()),
        "operaciones": operaciones,
        "comisiones": comisiones,
        "ganadoras": ganadoras / operaciones if operaciones else None,
        "bh_rendimiento": bh_total.metricas.rendimiento,
        "bh_drawdown": bh_total.metricas.drawdown_maximo,
        "le_gana_a_no_operar": rendimiento > 0,
        "le_gana_a_comprar_y_mantener": rendimiento > bh_total.metricas.rendimiento,
        "mensual_oos": mensual(rendimiento, dias_oos),
        "mensual_bh": mensual(bh_total.metricas.rendimiento, dias_oos),
        "mensual_entrenamiento_promedio": float(np.mean([p["mensual_entrenamiento"] for p in pliegues])),
        "mensual_prueba_promedio": float(np.mean([p["mensual_prueba"] for p in pliegues])),
        "cambios_de_parametros": cambios,
    }
    return ResultadoWalkForward(resumen, pliegues, corridas, ts, curva, capital_bh)
