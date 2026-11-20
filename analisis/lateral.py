"""Exploración: ¿en los mercados laterales el precio rebota más que en los de tendencia?

    python analisis/lateral.py

"Lateral" se mide con el índice de eficiencia de Kaufman en 72 velas de 1h (3 días):
cuánto avanzó el precio entre todo lo que se movió. Cerca de 0 = va de lado; cerca de 1 = va
directo en una dirección.

Para cada hora se compara el rendimiento de las 24 h ANTERIORES con el de las 24 h SIGUIENTES:
- correlación negativa = rebote (lo que bajó tiende a subir, y al revés);
- correlación positiva = inercia (lo que bajó tiende a seguir bajando).
Se mide por quintil del índice de eficiencia (cortes del entrenamiento), en entrenamiento
(2020-2023) y en prueba (2024 a hoy). Además: después de una baja fuerte (el 10% peor de las 24 h
previas), cuánto sube en promedio en las 24 h siguientes, frente al costo de ~0.30% por operación.

Usa solo pares que ya se exploraron. Los reservados (ATOM, ETC y XLM) no se tocan aquí.
"""

import sqlite3

import numpy as np
import pandas as pd

from tradinglab.config import cargar_config

PARES = ("BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LTCUSDT", "LINKUSDT")
VENTANA_EFICIENCIA = 72
HORAS = 24
CORTE = pd.Timestamp("2024-01-01", tz="UTC")

con = sqlite3.connect(f"file:{cargar_config().ruta_base.as_posix()}?mode=ro", uri=True)


def eficiencia(cierre: pd.Series, ventana: int) -> pd.Series:
    avance = (cierre - cierre.shift(ventana)).abs()
    recorrido = cierre.diff().abs().rolling(ventana).sum()
    return avance / recorrido


resumen = []
print(f"Correlación entre las {HORAS} h anteriores y las {HORAS} h siguientes, por quintil de eficiencia "
      f"(1 = más lateral, 5 = más tendencia). Entrenamiento / prueba.\n")
print(f"{'par':9} " + "  ".join(f"{'q' + str(q):>13}" for q in range(1, 6)) +
      f"  {'rebote tras baja fuerte, lateral (q1)':>38}  {'en tendencia (q5)':>18}")
for par in PARES:
    df = pd.read_sql_query("SELECT ts, cierre FROM velas WHERE simbolo=? AND intervalo='1h' ORDER BY ts", con,
                           params=(par,))
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    c = df["cierre"]
    d = pd.DataFrame({
        "ef": eficiencia(c, VENTANA_EFICIENCIA),
        "antes": c / c.shift(HORAS) - 1,
        "despues": c.shift(-HORAS) / c - 1,
    }).dropna()
    ent, pru = d[d.index < CORTE], d[d.index >= CORTE]
    cortes = np.quantile(ent["ef"], [0.2, 0.4, 0.6, 0.8])
    baja_fuerte = ent["antes"].quantile(0.10)
    celdas, rebotes = [], {}
    for q in range(5):
        corr = []
        for periodo in (ent, pru):
            en_q = np.searchsorted(cortes, periodo["ef"].to_numpy(), side="right") == q
            corr.append(periodo.loc[en_q, "antes"].corr(periodo.loc[en_q, "despues"]))
            if q in (0, 4):
                tras_baja = en_q & (periodo["antes"] <= baja_fuerte).to_numpy()
                rebotes.setdefault(q, []).append(periodo.loc[tras_baja, "despues"].mean())
        celdas.append(f"{corr[0]:+.2f}/{corr[1]:+.2f}")
        resumen.append({"par": par, "q": q + 1, "ent": corr[0], "pru": corr[1]})
    print(f"{par:9} " + "  ".join(f"{x:>13}" for x in celdas) +
          f"  {rebotes[0][0]:>+18.2%} / {rebotes[0][1]:>+7.2%}        {rebotes[4][0]:>+7.2%} / {rebotes[4][1]:>+7.2%}")

r = pd.DataFrame(resumen)
print("\nPromedio de los 9 pares:")
for q in range(1, 6):
    fila = r[r["q"] == q]
    print(f"  quintil {q}: entrenamiento {fila['ent'].mean():+.3f}, prueba {fila['pru'].mean():+.3f}")
print("\nNegativo = rebote; positivo = inercia. Las ventanas de 24 h se enciman entre horas vecinas, así que "
      "cada correlación se apoya en muchas menos observaciones independientes de las que parece.")
