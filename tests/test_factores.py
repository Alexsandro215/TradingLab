import io
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tradinglab import db
from tradinglab.backtest.datos import Serie, cargar_serie
from tradinglab.factores import descarga, eventos
from tradinglab.factores.tabla import DIA_MS, HORA_MS, tabla_factores
from tradinglab.recolector.descarga import kline_a_fila
from tradinglab.tiempo import fecha_a_ms

from fabrica import T0, UNA_HORA, kline


def zip_metricas(filas: list[str]) -> bytes:
    encabezado = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
                  "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("BTCUSDT-metrics.csv", "\n".join([encabezado, *filas]) + "\n")
    return buffer.getvalue()


def test_leer_zip_metricas():
    contenido = zip_metricas([
        "2022-01-01 00:00:00,BTCUSDT,100.5,4650000.25,,,,",
        "2022-01-01 00:05:00,BTCUSDT,101,4700000,1.2,1.5,0.9,1.1",
    ])
    filas = descarga.leer_zip_metricas(contenido, "BTCUSDT")
    assert filas[0] == ("BTCUSDT", fecha_a_ms("2022-01-01"), 100.5, 4650000.25, None, None, None, None)
    assert filas[1] == ("BTCUSDT", fecha_a_ms("2022-01-01T00:05"), 101.0, 4700000.0, 1.2, 1.5, 0.9, 1.1)


class FuturosFalso:
    def __init__(self, tasas):
        self.tasas = tasas  # lista de (ts, tasa)
        self.pedidos = []

    def get(self, ruta, parametros):
        assert ruta == "/fapi/v1/fundingRate"
        self.pedidos.append(parametros["startTime"])
        filas = [t for t in self.tasas if t[0] >= parametros["startTime"]][: parametros["limit"]]
        return [{"symbol": "BTCUSDT", "fundingTime": ts, "fundingRate": f"{tasa:.8f}"} for ts, tasa in filas]


def test_funding_incremental(monkeypatch):
    monkeypatch.setattr(descarga, "LIMITE_FUNDING", 3)
    con = db.conectar(":memory:")
    tasas = [(T0 + i * 8 * HORA_MS, 0.0001 * (i + 1)) for i in range(7)]
    cliente = FuturosFalso(tasas)
    assert descarga.descargar_funding(con, cliente, "BTCUSDT", T0) == 7
    assert len(cliente.pedidos) == 3  # 3 + 3 + 1
    cliente.tasas.append((T0 + 7 * 8 * HORA_MS, 0.0005))
    assert descarga.descargar_funding(con, cliente, "BTCUSDT", T0) == 1
    assert con.execute("SELECT COUNT(*) FROM funding").fetchone()[0] == 8


def test_primer_dia_disponible():
    inicio, fin = date(2020, 1, 1), date(2022, 12, 31)
    primero = date(2021, 12, 1)
    encontrado = descarga.primer_dia_disponible(lambda d: d >= primero, inicio, fin)
    assert primero - timedelta(days=3) <= encontrado <= primero
    # Con huecos sueltos después del inicio, nunca empieza tarde.
    huecos = {primero + timedelta(days=k) for k in (1, 7, 30, 100, 200)}
    encontrado = descarga.primer_dia_disponible(lambda d: d >= primero and d not in huecos, inicio, fin)
    assert primero - timedelta(days=3) <= encontrado <= primero
    assert descarga.primer_dia_disponible(lambda d: True, inicio, fin) == inicio
    assert descarga.primer_dia_disponible(lambda d: False, inicio, fin) is None


class ArchivosFalsos(descarga.ArchivosBinance):
    def __init__(self, dias_con_archivo):
        super().__init__("https://falso")
        self.dias = dias_con_archivo

    def bajar(self, ruta):
        dia = date.fromisoformat(ruta[-14:-4])
        if dia not in self.dias:
            return None
        return zip_metricas([f"{dia} 00:00:00,BTCUSDT,100,1000,1,1,1,1", f"{dia} 00:05:00,BTCUSDT,101,1010,1,1,1,1"])


def test_metricas_buscan_el_inicio_y_siguen_donde_se_quedaron():
    con = db.conectar(":memory:")
    primero = date(2021, 3, 10)
    dias = {primero + timedelta(days=i) for i in range(20)} - {primero + timedelta(days=5)}  # falta un día
    archivos = ArchivosFalsos(dias)
    filas, faltan = descarga.descargar_metricas(con, archivos, "BTCUSDT", date(2020, 1, 1), primero + timedelta(days=19))
    assert filas == 19 * 2  # el hueco del día 5 no hace perder los días anteriores
    assert 1 <= faltan <= 4  # el hueco, y quizá unos días antes del inicio real
    # Segunda corrida: empieza después del último día guardado.
    archivos.dias.add(primero + timedelta(days=20))
    filas, faltan = descarga.descargar_metricas(con, archivos, "BTCUSDT", date(2020, 1, 1), primero + timedelta(days=20))
    assert (filas, faltan) == (2, 0)


def test_miedo_codicia():
    con = db.conectar(":memory:")
    datos = {"data": [{"value": "12", "value_classification": "Extreme Fear", "timestamp": str(T0 // 1000 + 86400)},
                      {"value": "55", "value_classification": "Greed", "timestamp": str(T0 // 1000)}]}
    assert descarga.descargar_miedo_codicia(con, "url", obtener_json=lambda url: datos) == 2
    assert con.execute("SELECT valor FROM miedo_codicia ORDER BY ts").fetchall() == [(55,), (12,)]


def _serie_con_velas(con, n=200, simbolo="BTCUSDT"):
    precios = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, n)))
    db.insertar_velas(con, [kline_a_fila(simbolo, "1h", kline(T0 + i * UNA_HORA, UNA_HORA, float(p), volumen=2.0))
                            for i, p in enumerate(precios)])
    return cargar_serie(con, simbolo, "1h")


def test_tabla_alinea_sin_ver_el_futuro():
    con = db.conectar(":memory:")
    serie = _serie_con_velas(con)
    # Funding cobrado justo al cierre de la vela 7 (T0 + 8 h) y otro 3 ms después del cierre de la vela 15.
    con.executemany("INSERT INTO funding VALUES ('BTCUSDT', ?, ?)",
                    [(T0 + 8 * HORA_MS, 0.0001), (T0 + 16 * HORA_MS + 3, 0.0003)])
    # Miedo y codicia del 1 de enero: solo se usa desde el 2 de enero.
    con.execute("INSERT INTO miedo_codicia VALUES (?, 40, 'Fear')", (T0,))
    con.executemany("INSERT INTO metricas_futuros (simbolo, ts, interes_abierto) VALUES ('BTCUSDT', ?, ?)",
                    [(T0 + i * 5 * 60_000, 1000.0 + i) for i in range(12 * 60)])
    f = tabla_factores(con, serie)

    assert np.isnan(f.loc[6, "funding"])  # la vela 6 cierra a las 7:00, antes del cobro
    assert f.loc[7, "funding"] == 0.0001  # la vela 7 cierra a las 8:00, justo en el cobro
    assert f.loc[15, "funding"] == 0.0001  # el cobro de las 16:00:00.003 llegó después de su cierre
    assert f.loc[16, "funding"] == 0.0003
    assert np.isnan(f.loc[25, "funding"])  # 9 h sin cobros: el dato es viejo y se descarta

    assert np.isnan(f.loc[22, "miedo_codicia"])  # cierra a las 23:00 del 1 de enero
    assert f.loc[23, "miedo_codicia"] == 40  # cierra a las 00:00 del 2 de enero

    # Interés abierto: 12 registros por hora. Al cierre de la vela 30 (31 h) contra 24 h antes (7 h).
    assert f.loc[30, "oi_cambio_24h"] == pytest.approx((1000 + 31 * 12) / (1000 + 7 * 12) - 1)
    assert np.isnan(f.loc[10, "oi_cambio_24h"])  # todavía no hay 24 h de historia

    # Flujo: en las velas de prueba la compra agresiva es la mitad del volumen.
    assert f.loc[50, "flujo_taker_24h"] == pytest.approx(0.5)
    assert np.isnan(f.loc[10, "flujo_taker_24h"])
    assert f.loc[30, "rendimiento_24h"] == pytest.approx(serie.cierre[30] / serie.cierre[6] - 1)


def test_tabla_no_cambia_si_se_agregan_datos_futuros():
    con = db.conectar(":memory:")
    serie = _serie_con_velas(con)
    con.executemany("INSERT INTO funding VALUES ('BTCUSDT', ?, ?)", [(T0 + i * 8 * HORA_MS, 0.0001 * i) for i in range(10)])
    antes = tabla_factores(con, serie)
    con.executemany("INSERT INTO funding VALUES ('BTCUSDT', ?, ?)", [(T0 + i * 8 * HORA_MS, 0.0001 * i) for i in range(10, 30)])
    despues = tabla_factores(con, serie)
    hasta = 8 * 10 - 1  # velas que cierran antes del primer cobro agregado
    pd.testing.assert_series_equal(antes["funding"][:hasta], despues["funding"][:hasta])


def test_caidas_independientes():
    es = np.zeros(100, dtype=bool)
    es[[10, 11, 12, 40, 41, 90]] = True
    assert eventos.caidas_independientes(es, separacion=24) == 3
    assert eventos.caidas_independientes(np.zeros(5, dtype=bool), 24) == 0


def _base_para_eventos(con, predictivo: bool):
    """Velas con caídas fuertes ocasionales; el funding avisa de ellas si `predictivo`."""
    rng = np.random.default_rng(11)
    n = 24 * 900  # unos 2.5 años de velas de 1h
    cambios = rng.normal(0, 0.004, n)
    aviso = np.zeros(n, dtype=bool)
    for inicio in rng.choice(np.arange(100, n - 100), size=120, replace=False):
        cambios[inicio + 1: inicio + 13] -= 0.01  # caída de ~11% en las 12 h siguientes
        aviso[inicio - 5: inicio + 1] = True  # el factor avisa durante las 6 h previas
    precios = 100 * np.exp(np.cumsum(cambios))
    db.insertar_velas(con, [kline_a_fila("BTCUSDT", "1h", kline(T0 + i * UNA_HORA, UNA_HORA, float(p)))
                            for i, p in enumerate(precios)])
    tasas = []
    for i in range(n):
        # Un cobro por hora para que cada vela tenga su dato (en la realidad es cada 8 h).
        alto = aviso[i] if predictivo else rng.random() < aviso.mean()
        tasas.append((T0 + (i + 1) * UNA_HORA, 0.002 if alto else 0.0001 + rng.normal(0, 0.00002)))
    con.executemany("INSERT INTO funding VALUES ('BTCUSDT', ?, ?)", tasas)
    return T0 + 24 * 600 * UNA_HORA  # corte: los primeros 600 días son entrenamiento


def test_eventos_detecta_un_factor_que_avisa():
    con = db.conectar(":memory:")
    corte = _base_para_eventos(con, predictivo=True)
    r = eventos.estudiar_serie(con, "BTCUSDT", "1h", horizonte_h=24, corte_ms=corte)
    funding = next(f for f in r["factores"] if f["factor"] == "funding")
    assert funding["evaluado"] and funding["quintil_riesgoso"] == 5
    assert funding["lift_entrenamiento"] > 1.25 and funding["lift_prueba"] > 1.25
    assert funding["se_sostiene"]
    # Antes de cada caída la volatilidad es normal: el aviso del funding no lo explica la volatilidad.
    assert funding["sobre_volatilidad_entrenamiento"] > 1.2 and funding["sobre_volatilidad_prueba"] > 1.2
    assert funding["agrega_sobre_volatilidad"]
    volatilidad = next(f for f in r["factores"] if f["factor"] == "volatilidad_24h")
    assert not volatilidad["agrega_sobre_volatilidad"]  # una referencia nunca "agrega" sobre sí misma
    assert r["entrenamiento"]["caidas_independientes"] > 20


def test_eventos_no_inventa_un_factor_que_no_avisa():
    con = db.conectar(":memory:")
    corte = _base_para_eventos(con, predictivo=False)
    r = eventos.estudiar_serie(con, "BTCUSDT", "1h", horizonte_h=24, corte_ms=corte)
    funding = next(f for f in r["factores"] if f["factor"] == "funding")
    assert not funding["se_sostiene"]
    assert not funding["agrega_sobre_volatilidad"]
    # Factores sin datos (sin métricas ni miedo y codicia) quedan marcados como no evaluados.
    assert not next(f for f in r["factores"] if f["factor"] == "miedo_codicia")["evaluado"]
