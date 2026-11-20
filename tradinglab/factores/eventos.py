"""Estudio de eventos: ¿algún factor avisa ANTES de las caídas fuertes?

Para cada vela se mide lo que pasa en las `horizonte` horas siguientes:
- "caída" = el rendimiento de las próximas horas está en el peor `cuantil` (5%). El umbral se
  calcula SOLO con el periodo de entrenamiento.
- Cada factor se parte en quintiles con los cortes del entrenamiento, y se mide la probabilidad
  de caída en cada quintil.

El quintil con más caídas en entrenamiento se busca luego en el periodo de prueba (que no se usó
para nada). Un factor solo "se sostiene" si ese mismo quintil también concentra caídas en la
prueba. Es la misma lógica fuera de muestra del walk-forward.

Cuidados:
- Las ventanas de las próximas horas se enciman entre velas vecinas, así que las observaciones
  no son independientes. Por eso se reporta cuántas caídas INDEPENDIENTES hubo (separadas por
  más del horizonte): es el tamaño de muestra real, y suele ser chico.
- La volatilidad reciente predice movimientos grandes en cualquier dirección. Un factor que solo
  repite lo que dice la volatilidad no agrega nada; por eso la volatilidad va como referencia.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradinglab.backtest.datos import cargar_serie
from tradinglab.factores.tabla import FACTORES, REFERENCIAS, tabla_factores
from tradinglab.tiempo import duracion_ms

QUINTILES = 5
# Un factor "se sostiene" si su quintil más riesgoso tiene al menos esta proporción de la tasa
# base de caídas, tanto en entrenamiento como en prueba.
LIFT_MINIMO = 1.25
# Un factor "agrega algo más allá de la volatilidad" si en su quintil riesgoso hay al menos esta
# proporción de las caídas que la volatilidad sola predeciría, en entrenamiento y en prueba.
SOBRE_VOLATILIDAD_MINIMO = 1.2
# Menos observaciones que esto en un periodo: no se evalúa.
MINIMO_FILAS = 500


@dataclass
class Periodo:
    filas: int
    caidas_independientes: int
    tasa_base: float  # probabilidad de caída en todo el periodo


def caidas_independientes(es_caida: np.ndarray, separacion: int) -> int:
    """Cuántos grupos de caídas hay, si dos caídas a menos de `separacion` velas son la misma."""
    indices = np.flatnonzero(es_caida)
    if len(indices) == 0:
        return 0
    return int(1 + np.sum(np.diff(indices) > separacion))


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Correlación de rangos (Spearman) sin depender de scipy."""
    return float(a.rank().corr(b.rank()))


def _por_quintil(valores: pd.Series, futuro: pd.Series, caida: pd.Series, cortes: np.ndarray) -> list[dict[str, Any]]:
    grupo = np.searchsorted(cortes, valores.to_numpy(), side="right")  # 0..QUINTILES-1
    filas = []
    for q in range(QUINTILES):
        en_q = grupo == q
        n = int(en_q.sum())
        filas.append({
            "quintil": q + 1,
            "filas": n,
            "p_caida": float(caida[en_q].mean()) if n else None,
            "rendimiento_medio": float(futuro[en_q].mean()) if n else None,
        })
    return filas


def estudiar_serie(
    con: sqlite3.Connection,
    simbolo: str,
    intervalo: str,
    horizonte_h: int,
    corte_ms: int,
    cuantil: float = 0.05,
) -> dict[str, Any]:
    serie = cargar_serie(con, simbolo, intervalo)
    factores = tabla_factores(con, serie)
    pasos = max(1, horizonte_h * 3_600_000 // duracion_ms(intervalo))
    cierre = pd.Series(serie.cierre)
    futuro = cierre.shift(-pasos) / cierre - 1  # lo que pasa DESPUÉS del cierre de la vela
    ts = pd.Series(serie.ts)
    valido = futuro.notna()
    entrenamiento = valido & (ts < corte_ms)
    prueba = valido & (ts >= corte_ms)
    if entrenamiento.sum() < MINIMO_FILAS or prueba.sum() < MINIMO_FILAS:
        raise ValueError(f"{simbolo} {intervalo}: no hay suficientes velas antes y después del corte")

    umbral = float(futuro[entrenamiento].quantile(cuantil))
    caida = futuro <= umbral

    def periodo(mascara: pd.Series) -> Periodo:
        return Periodo(int(mascara.sum()), caidas_independientes((caida & mascara).to_numpy(), pasos),
                       float(caida[mascara].mean()))

    resultado: dict[str, Any] = {
        "simbolo": simbolo,
        "intervalo": intervalo,
        "horizonte_h": horizonte_h,
        "corte_ms": corte_ms,
        "umbral_caida": umbral,
        "inicio_ms": int(serie.ts[0]),
        "fin_ms": int(serie.ts[-1]),
        "entrenamiento": periodo(entrenamiento).__dict__,
        "prueba": periodo(prueba).__dict__,
        "factores": [],
    }

    # Estratos de volatilidad (quintiles con los cortes del entrenamiento). Sirven para medir si un
    # factor agrega algo más allá de la volatilidad: se compara cuántas caídas hubo en su quintil
    # riesgoso con cuántas habría si solo importara la volatilidad (tasa de caídas de cada
    # estrato de volatilidad, en el mismo periodo).
    volatilidad = factores["volatilidad_24h"]
    hay_vol = volatilidad.notna()
    cortes_vol = np.unique(np.quantile(volatilidad[entrenamiento & hay_vol], np.linspace(0, 1, QUINTILES + 1)[1:-1]))
    estrato = pd.Series(np.searchsorted(cortes_vol, volatilidad.to_numpy(), side="right"), index=volatilidad.index)

    def sobre_volatilidad(periodo_: pd.Series, seleccion: pd.Series) -> float | None:
        filas = periodo_ & hay_vol
        tasas = caida[filas].groupby(estrato[filas]).mean()
        elegidas = filas & seleccion
        if not elegidas.any():
            return None
        esperadas = float(estrato[elegidas].map(tasas).sum())
        return float(caida[elegidas].sum()) / esperadas if esperadas > 0 else None

    for nombre in FACTORES:
        valores = factores[nombre]
        ent = entrenamiento & valores.notna()
        pru = prueba & valores.notna()
        fila: dict[str, Any] = {"factor": nombre, "referencia": nombre in REFERENCIAS,
                                "desde_ms": int(ts[valores.notna()].min()) if valores.notna().any() else None,
                                "filas_entrenamiento": int(ent.sum()), "filas_prueba": int(pru.sum())}
        if ent.sum() < MINIMO_FILAS or pru.sum() < MINIMO_FILAS:
            fila["evaluado"] = False
            resultado["factores"].append(fila)
            continue
        cortes = np.unique(np.quantile(valores[ent], np.linspace(0, 1, QUINTILES + 1)[1:-1]))
        q_ent = _por_quintil(valores[ent], futuro[ent], caida[ent], cortes)
        q_pru = _por_quintil(valores[pru], futuro[pru], caida[pru], cortes)
        base_ent, base_pru = float(caida[ent].mean()), float(caida[pru].mean())
        riesgoso = max((q for q in q_ent if q["filas"]), key=lambda q: q["p_caida"])["quintil"]
        p_ent = q_ent[riesgoso - 1]["p_caida"]
        p_pru = q_pru[riesgoso - 1]["p_caida"]
        lift_ent = p_ent / base_ent if base_ent else None
        lift_pru = p_pru / base_pru if (base_pru and p_pru is not None) else None
        en_riesgoso = pd.Series(np.searchsorted(cortes, valores.to_numpy(), side="right") == riesgoso - 1,
                                index=valores.index) & valores.notna()
        vol_ent = sobre_volatilidad(entrenamiento, en_riesgoso)
        vol_pru = sobre_volatilidad(prueba, en_riesgoso)
        se_sostiene = bool(lift_ent and lift_pru and lift_ent >= LIFT_MINIMO and lift_pru >= LIFT_MINIMO)
        fila.update({
            "evaluado": True,
            "cortes": cortes.tolist(),
            "quintiles_entrenamiento": q_ent,
            "quintiles_prueba": q_pru,
            "base_entrenamiento": base_ent,
            "base_prueba": base_pru,
            "quintil_riesgoso": riesgoso,
            "p_caida_entrenamiento": p_ent,
            "p_caida_prueba": p_pru,
            "lift_entrenamiento": lift_ent,
            "lift_prueba": lift_pru,
            "correlacion_entrenamiento": spearman(valores[ent], futuro[ent]),
            "correlacion_prueba": spearman(valores[pru], futuro[pru]),
            "se_sostiene": se_sostiene,
            "sobre_volatilidad_entrenamiento": vol_ent,
            "sobre_volatilidad_prueba": vol_pru,
            "agrega_sobre_volatilidad": bool(
                se_sostiene and nombre not in REFERENCIAS and vol_ent and vol_pru
                and vol_ent >= SOBRE_VOLATILIDAD_MINIMO and vol_pru >= SOBRE_VOLATILIDAD_MINIMO
            ),
        })
        resultado["factores"].append(fila)
    return resultado
