import numpy as np
import pytest

from tradinglab import db
from tradinglab.backtest.costos import Costos
from tradinglab.backtest.datos import cargar_serie
from tradinglab.backtest.estrategias import obtener
from tradinglab.backtest.motor import simular
from tradinglab.papel.operador import ConfigSesion, Operador, borrar_sesion, leer_sesion, resumen_sesion
from tradinglab.recolector.descarga import kline_a_fila

from fabrica import CINCO_MIN, T0, kline

COSTOS = Costos(0.001, 0.0005)


def sesion(**cambios):
    datos = dict(nombre="prueba", simbolo="BTCUSDT", intervalo="5m", estrategia="momentum",
                 parametros={"ventana": 3}, capital_inicial=1000.0, fraccion=1.0, costos=COSTOS)
    datos.update(cambios)
    return ConfigSesion(**datos)


def mensaje(k, cerrada, operaciones=10, precio=None):
    """Objeto 'k' de un evento kline del websocket de Binance, a partir de una vela simulada."""
    return {"t": k[0], "o": k[1], "h": k[2], "l": k[3], "c": precio if precio is not None else k[4], "v": k[5],
            "q": k[7], "n": operaciones, "V": k[9], "Q": k[10], "x": cerrada}


def precios(n, semilla=2):
    rng = np.random.default_rng(semilla)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))


def base_con_historia(n_historia):
    con = db.conectar(":memory:")
    p = precios(n_historia + 200)
    velas = [kline(T0 + i * CINCO_MIN, CINCO_MIN, float(p[i])) for i in range(n_historia + 200)]
    db.insertar_velas(con, [kline_a_fila("BTCUSDT", "5m", k) for k in velas[:n_historia]])
    return con, velas


def test_papel_reproduce_al_backtest():
    """Velas en vivo una por una: las operaciones deben ser exactamente las del motor de backtest."""
    con, velas = base_con_historia(50)
    operador = Operador(con, sesion())
    operador.recalcular()
    # Sin al_conectar(): simula que ya estaba conectado cuando abrió la primera vela.
    for k in velas[50:]:
        # Primero llegan actualizaciones de la vela abierta y luego su cierre.
        operador.procesar_kline(mensaje(k, cerrada=False))
        operador.procesar_kline(mensaje(k, cerrada=True))

    # El mismo periodo en el motor de backtest.
    serie = cargar_serie(con, "BTCUSDT", "5m")
    objetivo = obtener("momentum").objetivo(serie.velas, {"ventana": 3})
    r = simular(serie, objetivo, inicio=50, costos=COSTOS)
    compras_motor = [(e.ts, round(e.precio, 6)) for e in r.ejecuciones if e.lado == "compra"]
    ops = con.execute("SELECT ts, lado, precio FROM papel_operaciones ORDER BY id").fetchall()
    compras_papel = [(ts, round(precio, 6)) for ts, lado, precio in ops if lado == "compra"]
    assert len(compras_papel) > 5
    assert compras_papel == compras_motor
    # El motor cierra la posición al final de la ventana; el papel la deja abierta. Fuera de eso, igual.
    ventas_motor = [(e.ts, round(e.precio, 6)) for e in r.ejecuciones if e.lado == "venta" and e.motivo == "señal"]
    assert [(ts, round(p, 6)) for ts, lado, p in ops if lado == "venta"] == ventas_motor


def test_conexion_a_mitad_de_vela_usa_el_precio_actual():
    con, velas = base_con_historia(60)
    # Fuerza una señal de compra: cierres que suben.
    operador = Operador(con, sesion(parametros={"ventana": 1}))
    con.execute("UPDATE velas SET cierre = cierre * 1.05 WHERE ts = ?", (velas[59][0],))
    assert operador.recalcular() == 1
    operador.al_conectar()
    k = velas[60]
    operador.procesar_kline(mensaje(k, cerrada=False, precio="123.0"))
    precio = con.execute("SELECT precio FROM papel_operaciones").fetchone()[0]
    assert precio == pytest.approx(123.0 * (1 + COSTOS.deslizamiento))  # precio actual, no la apertura


def test_vela_sin_operaciones_no_ejecuta():
    con, velas = base_con_historia(60)
    operador = Operador(con, sesion(parametros={"ventana": 1}))
    con.execute("UPDATE velas SET cierre = cierre * 1.05 WHERE ts = ?", (velas[59][0],))
    operador.recalcular()
    operador.procesar_kline(mensaje(velas[60], cerrada=False, operaciones=0))
    assert con.execute("SELECT COUNT(*) FROM papel_operaciones").fetchone()[0] == 0
    operador.procesar_kline(mensaje(velas[60], cerrada=False, operaciones=3))
    assert con.execute("SELECT COUNT(*) FROM papel_operaciones").fetchone()[0] == 1


def test_la_sesion_se_retoma_y_se_resume():
    con, velas = base_con_historia(50)
    operador = Operador(con, sesion())
    operador.recalcular()
    for k in velas[50:120]:
        operador.procesar_kline(mensaje(k, cerrada=False))
        operador.procesar_kline(mensaje(k, cerrada=True))
    efectivo, cantidad = operador.efectivo, operador.cantidad

    retomado = Operador(con, leer_sesion(con, "prueba"))
    assert (retomado.efectivo, retomado.cantidad, retomado.objetivo) == (efectivo, cantidad, operador.objetivo)
    assert leer_sesion(con, "prueba").misma_configuracion(sesion())
    assert not leer_sesion(con, "prueba").misma_configuracion(sesion(parametros={"ventana": 4}))

    r = resumen_sesion(con, "prueba")
    assert r["capital"] == pytest.approx(operador.capital)
    assert r["bh_rendimiento"] is not None
    assert con.execute("SELECT COUNT(*) FROM papel_capital WHERE sesion = 'prueba'").fetchone()[0] == 71

    borrar_sesion(con, "prueba")
    assert leer_sesion(con, "prueba") is None
    assert resumen_sesion(con, "prueba") is None
