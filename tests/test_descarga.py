from tradinglab import db
from tradinglab.recolector.descarga import descargar_serie, kline_a_fila

from fabrica import CINCO_MIN, T0, FuenteFalsa, kline, serie


def contar(con) -> int:
    return con.execute("SELECT COUNT(*) FROM velas").fetchone()[0]


def test_convierte_los_12_campos():
    k = kline(T0, CINCO_MIN, precio=200.0, volumen=3.0)
    assert kline_a_fila("BTCUSDT", "5m", k) == (
        "BTCUSDT", "5m", T0, 200.0, 202.0, 198.0, 201.0, 3.0, 600.0, 10, 1.5, 300.0,
    )


def test_descarga_completa_en_varios_lotes():
    con = db.conectar(":memory:")
    # 10 velas cerradas; "ahora" es justo el cierre de la décima.
    fuente = FuenteFalsa(serie(T0, 10, CINCO_MIN), ahora=T0 + 10 * CINCO_MIN, limite=3)
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert r.insertadas == 10
    assert r.lotes == 4  # 3 + 3 + 3 + 1
    assert r.ultima_ts == T0 + 9 * CINCO_MIN
    assert contar(con) == 10


def test_segunda_corrida_no_duplica_ni_pide_de_mas():
    con = db.conectar(":memory:")
    fuente = FuenteFalsa(serie(T0, 10, CINCO_MIN), ahora=T0 + 10 * CINCO_MIN, limite=3)
    descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    fuente.pedidos.clear()
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert r.insertadas == 0
    assert fuente.pedidos == []  # ya está al día: ni siquiera pregunta
    assert contar(con) == 10


def test_reanuda_desde_la_ultima_vela():
    con = db.conectar(":memory:")
    todas = serie(T0, 10, CINCO_MIN)
    db.insertar_velas(con, [kline_a_fila("BTCUSDT", "5m", k) for k in todas[:6]])
    fuente = FuenteFalsa(todas, ahora=T0 + 10 * CINCO_MIN)
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert fuente.pedidos[0] == T0 + 6 * CINCO_MIN
    assert r.insertadas == 4
    assert contar(con) == 10


def test_descarta_la_vela_abierta():
    con = db.conectar(":memory:")
    # 6 velas en Binance, pero "ahora" cae a la mitad de la sexta.
    fuente = FuenteFalsa(serie(T0, 6, CINCO_MIN), ahora=T0 + 5 * CINCO_MIN + 1000)
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert r.insertadas == 5
    assert db.ultima_ts(con, "BTCUSDT", "5m") == T0 + 4 * CINCO_MIN
    # Cuando la vela cierra, la siguiente corrida la guarda.
    fuente.ahora = T0 + 6 * CINCO_MIN
    assert descargar_serie(con, fuente, "BTCUSDT", "5m", T0).insertadas == 1


def test_huecos_no_se_rellenan_y_no_atoran_la_descarga():
    con = db.conectar(":memory:")
    # Faltan las velas 3, 4 y 5 (mantenimiento), y el hueco cae entre dos lotes.
    fuente = FuenteFalsa(serie(T0, 12, CINCO_MIN, saltar={3, 4, 5}), ahora=T0 + 12 * CINCO_MIN, limite=3)
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert r.insertadas == 9
    assert contar(con) == 9
    assert db.ultima_ts(con, "BTCUSDT", "5m") == T0 + 11 * CINCO_MIN


def test_par_sin_velas_termina():
    con = db.conectar(":memory:")
    fuente = FuenteFalsa([], ahora=T0 + 100 * CINCO_MIN)
    r = descargar_serie(con, fuente, "BTCUSDT", "5m", T0)
    assert r.insertadas == 0
    assert r.ultima_ts is None
    assert len(fuente.pedidos) == 1


def test_inicio_anterior_al_listado():
    con = db.conectar(":memory:")
    # El par empezó a cotizar después de la fecha de inicio pedida.
    listado = T0 + 50 * CINCO_MIN
    fuente = FuenteFalsa(serie(listado, 5, CINCO_MIN), ahora=listado + 5 * CINCO_MIN)
    r = descargar_serie(con, fuente, "ZECUSDT", "5m", T0)
    assert r.insertadas == 5
