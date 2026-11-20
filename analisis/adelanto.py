"""Exploración: ¿un mercado se adelanta a otro?

    python analisis/adelanto.py

Lee las velas de la base (BTC, ETH, ZEC, SOL, BNB, XRP, ADA, LTC, LINK y PAXG en 1h; BTC, ETH y
ZEC en 5m) y baja de FRED (Reserva Federal de San Luis, público y sin llaves) el S&P 500, el
Nasdaq y el índice del dólar a datos/externos/. Resultados y lectura en docs/RESULTADOS.md.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from tradinglab.config import RAIZ, cargar_config

BASE = cargar_config().ruta_base
CSV = RAIZ / "datos" / "externos"
CORTE = pd.Timestamp("2024-01-01", tz="UTC")
con = sqlite3.connect(f"file:{BASE.as_posix()}?mode=ro", uri=True)

CSV.mkdir(parents=True, exist_ok=True)
for nombre in ("SP500", "NASDAQCOM", "DTWEXBGS"):
    if not (CSV / f"{nombre}.csv").exists():
        respuesta = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={nombre}&cosd=2019-12-01", timeout=60)
        respuesta.raise_for_status()
        (CSV / f"{nombre}.csv").write_bytes(respuesta.content)


def serie(simbolo, intervalo):
    df = pd.read_sql_query("SELECT ts, cierre FROM velas WHERE simbolo=? AND intervalo=? ORDER BY ts", con,
                           params=(simbolo, intervalo))
    return pd.Series(df["cierre"].to_numpy(), index=pd.to_datetime(df["ts"], unit="ms", utc=True), name=simbolo)


def analizar(a, b, ra, rb, extremo=0.05):
    """ra, rb: rendimientos alineados por periodo. ¿ra(t) dice algo de rb(t+1)?"""
    datos = pd.DataFrame({"ra": ra, "rb": rb}).dropna()
    datos["rb_sig"] = datos["rb"].shift(-1)
    datos["ra_sig"] = datos["ra"].shift(-1)
    datos = datos.dropna()
    ent, pru = datos[datos.index < CORTE], datos[datos.index >= CORTE]
    alto, bajo = ent["ra"].quantile(1 - extremo), ent["ra"].quantile(extremo)  # umbrales del entrenamiento
    fila = {"par": f"{a} -> {b}"}
    for nombre, d in (("ent", ent), ("pru", pru)):
        fila[f"juntos_{nombre}"] = d["ra"].corr(d["rb"])
        fila[f"{a}_adelanta_{nombre}"] = d["ra"].corr(d["rb_sig"])
        fila[f"{b}_adelanta_{nombre}"] = d["rb"].corr(d["ra_sig"])
        fila[f"tras_subida_{nombre}"] = d.loc[d["ra"] >= alto, "rb_sig"].mean()
        fila[f"tras_bajada_{nombre}"] = d.loc[d["ra"] <= bajo, "rb_sig"].mean()
        fila[f"n_{nombre}"] = len(d)
    return fila


def imprimir(titulo, filas, unidad):
    print(f"\n=== {titulo}")
    print(f"{'par':22} {'juntos ent/pru':>15} {'A adelanta ent/pru':>20} {'B adelanta ent/pru':>20} "
          f"{'B tras subida fuerte de A':>27} {'B tras bajada fuerte de A':>27}")
    for f in filas:
        a, b = f["par"].split(" -> ")
        print(f"{f['par']:22} {f['juntos_ent']:+7.2f}/{f['juntos_pru']:+5.2f}   "
              f"{f[f'{a}_adelanta_ent']:+9.3f}/{f[f'{a}_adelanta_pru']:+6.3f}   "
              f"{f[f'{b}_adelanta_ent']:+9.3f}/{f[f'{b}_adelanta_pru']:+6.3f}   "
              f"{f['tras_subida_ent']:+11.3%}/{f['tras_subida_pru']:+8.3%}   "
              f"{f['tras_bajada_ent']:+11.3%}/{f['tras_bajada_pru']:+8.3%}")
    n = filas[0]["n_ent"], filas[0]["n_pru"]
    print(f"   ({n[0]:,} {unidad} de entrenamiento y {n[1]:,} de prueba; con tantas observaciones, una "
          f"correlación de ±{2 / np.sqrt(n[1]):.3f} ya sería poco probable por azar)")


# 1) Criptos entre sí, velas de 1h: ¿BTC se adelanta a las demás, o al revés?
precios = {s: serie(s, "1h") for s in ("BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                                       "ADAUSDT", "LTCUSDT", "LINKUSDT", "PAXGUSDT")}
r = pd.DataFrame(precios).pct_change(fill_method=None)
filas = [analizar("BTC", s[:-4], r["BTCUSDT"], r[s]) for s in precios if s != "BTCUSDT"]
imprimir("Velas de 1h: BTC contra las demás (PAXG = oro)", filas, "horas")

# 2) Velas de 5m: los adelantos suelen ser de minutos.
r5 = pd.DataFrame({s: serie(s, "5m") for s in ("BTCUSDT", "ETHUSDT", "ZECUSDT")}).pct_change(fill_method=None)
filas = [analizar("BTC", s[:-4], r5["BTCUSDT"], r5[s]) for s in ("ETHUSDT", "ZECUSDT")]
filas.append(analizar("ETH", "ZEC", r5["ETHUSDT"], r5["ZECUSDT"]))
imprimir("Velas de 5m", filas, "velas de 5m")

# 3) Bolsa y dólar contra BTC y ETH, diario. La bolsa cierra 20:00-21:00 UTC: se usa el precio de
#    las criptos a las 21:00 UTC, así "el día" de las dos termina casi a la misma hora.
def fred(nombre):
    df = pd.read_csv(CSV / f"{nombre}.csv")
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    return pd.Series(s.to_numpy(), index=pd.to_datetime(df.iloc[:, 0]).dt.tz_localize("UTC") + pd.Timedelta(hours=21)).dropna()


diario = {}
for s in ("BTCUSDT", "ETHUSDT"):
    p = precios[s]
    diario[s] = p[p.index.hour == 20].copy()  # vela de las 20:00 = cierre a las 21:00
    diario[s].index = diario[s].index + pd.Timedelta(hours=1)
filas = []
for mercado in ("SP500", "NASDAQCOM", "DTWEXBGS"):
    m = fred(mercado)
    for s in ("BTCUSDT", "ETHUSDT"):
        juntos = pd.DataFrame({"m": m, "c": diario[s]}).dropna()  # solo días hábiles de la bolsa
        rm, rc = juntos["m"].pct_change(), juntos["c"].pct_change()
        filas.append(analizar(mercado.replace("COM", "").replace("DTWEXBGS", "DOLAR"), s[:-4], rm, rc, extremo=0.10))
imprimir("Diario: bolsa de EE. UU. y dólar contra BTC y ETH (de un cierre de bolsa al siguiente)", filas, "días")
print("\nCostos de ida y vuelta de una operación: ~0.30% en BTC/ETH (comisión 0.1% y deslizamiento 0.05% por lado).")
