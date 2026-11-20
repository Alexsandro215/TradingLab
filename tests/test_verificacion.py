from tradinglab import db
from tradinglab.config import cargar_config
from tradinglab.recolector import verificacion
from tradinglab.recolector.descarga import kline_a_fila

from fabrica import CINCO_MIN, T0, UNA_HORA, agregar, kline_sin_operaciones, serie


def guardar(con, simbolo, intervalo, klines):
    db.insertar_velas(con, [kline_a_fila(simbolo, intervalo, k) for k in klines])


def test_resumen_sin_huecos():
    con = db.conectar(":memory:")
    guardar(con, "BTCUSDT", "5m", serie(T0, 20, CINCO_MIN))
    r = verificacion.resumir_serie(con, "BTCUSDT", "5m")
    assert (r.total, r.primera_ts, r.ultima_ts) == (20, T0, T0 + 19 * CINCO_MIN)
    assert r.huecos == []
    assert r.invalidas == 0


def test_detecta_huecos():
    con = db.conectar(":memory:")
    guardar(con, "BTCUSDT", "5m", serie(T0, 20, CINCO_MIN, saltar={3, 4, 10}))
    r = verificacion.resumir_serie(con, "BTCUSDT", "5m")
    assert [(h.antes_ts, h.despues_ts, h.faltantes) for h in r.huecos] == [
        (T0 + 2 * CINCO_MIN, T0 + 5 * CINCO_MIN, 2),
        (T0 + 9 * CINCO_MIN, T0 + 11 * CINCO_MIN, 1),
    ]
    assert r.faltantes == 3


def test_detecta_velas_invalidas():
    con = db.conectar(":memory:")
    guardar(con, "BTCUSDT", "5m", serie(T0, 5, CINCO_MIN))
    con.execute("UPDATE velas SET maximo = cierre - 1 WHERE ts = ?", (T0 + 2 * CINCO_MIN,))
    r = verificacion.resumir_serie(con, "BTCUSDT", "5m")
    assert r.invalidas == 1
    assert r.ejemplos_invalidas == [T0 + 2 * CINCO_MIN]


def test_pares_cruzables():
    assert verificacion.pares_cruzables(["1h", "5m"]) == [("5m", "1h")]
    assert verificacion.pares_cruzables(["5m"]) == []
    assert verificacion.pares_cruzables(["5m", "1h", "1d"]) == [("5m", "1h"), ("1h", "1d")]


def test_cruce_5m_contra_1h_coincide():
    con = db.conectar(":memory:")
    finas = serie(T0, 36, CINCO_MIN)  # 3 horas completas
    guardar(con, "BTCUSDT", "5m", finas)
    guardar(con, "BTCUSDT", "1h", agregar(finas, UNA_HORA))
    c = verificacion.cruzar_intervalos(con, "BTCUSDT", "5m", "1h")
    assert (c.comparadas, c.diferentes, c.incompletas) == (3, 0, 0)


def test_cruce_ignora_velas_sin_operaciones():
    # Caso real de ZEC: la primera y la última vela de 5m de la hora no tuvieron operaciones
    # y Binance las llenó con el cierre anterior, que es más bajo que cualquier precio operado.
    con = db.conectar(":memory:")
    finas = serie(T0 - CINCO_MIN, 13, CINCO_MIN)
    finas[1] = kline_sin_operaciones(T0, CINCO_MIN, cierre_anterior="50.00000000")
    finas[12] = kline_sin_operaciones(T0 + 11 * CINCO_MIN, CINCO_MIN, cierre_anterior=finas[11][4])
    guardar(con, "ZECUSDT", "5m", finas)
    guardar(con, "ZECUSDT", "1h", agregar(finas[1:], UNA_HORA))
    c = verificacion.cruzar_intervalos(con, "ZECUSDT", "5m", "1h")
    assert (c.comparadas, c.diferentes) == (1, 0)


def test_cruce_con_hora_sin_ninguna_operacion():
    con = db.conectar(":memory:")
    finas = [kline_sin_operaciones(T0 + i * CINCO_MIN, CINCO_MIN, "50.00000000") for i in range(12)]
    guardar(con, "ZECUSDT", "5m", finas)
    guardar(con, "ZECUSDT", "1h", agregar(finas, UNA_HORA))
    c = verificacion.cruzar_intervalos(con, "ZECUSDT", "5m", "1h")
    assert (c.comparadas, c.diferentes) == (1, 0)


def test_cruce_detecta_diferencias_e_incompletas():
    con = db.conectar(":memory:")
    finas = serie(T0, 36, CINCO_MIN)
    guardar(con, "BTCUSDT", "1h", agregar(finas, UNA_HORA))
    # A la tercera hora le falta una vela de 5m.
    guardar(con, "BTCUSDT", "5m", [k for i, k in enumerate(finas) if i != 30])
    con.execute("UPDATE velas SET maximo = maximo + 1 WHERE intervalo = '1h' AND ts = ?", (T0,))
    c = verificacion.cruzar_intervalos(con, "BTCUSDT", "5m", "1h")
    assert (c.comparadas, c.diferentes, c.incompletas) == (2, 1, 1)
    assert c.ejemplos == [(T0, "maximo")]


def test_config_del_proyecto_es_valida():
    config = cargar_config()
    assert config.recolector.simbolos == ("BTCUSDT", "ETHUSDT", "ZECUSDT")
    assert config.recolector.intervalos == ("5m", "1h")
    assert config.recolector.inicio_ms == T0
    assert config.ruta_base.name == "tradinglab.sqlite"
