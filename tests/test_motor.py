import numpy as np
import pytest

from tradinglab.backtest.costos import Costos, comprar, vender
from tradinglab.backtest.motor import backtest, comprar_y_mantener, no_operar, simular
from tradinglab.backtest import estrategias

from fabrica import UNA_HORA, T0, caminata, serie_backtest

SIN_DESLIZAMIENTO = Costos(comision=0.001, deslizamiento=0.0)
APERTURAS = [100, 110, 120, 130, 140]
CIERRES = [105, 115, 125, 135, 145]


def test_costos_de_compra_y_venta():
    costos = Costos(comision=0.001, deslizamiento=0.01)
    c = comprar(1000, 100, costos)
    assert c.precio == pytest.approx(101)
    assert c.comision == pytest.approx(1)
    assert c.cantidad == pytest.approx(999 / 101)
    assert c.costo_deslizamiento == pytest.approx(999 / 101 * 1)
    v = vender(10, 100, costos)
    assert v.precio == pytest.approx(99)
    assert v.comision == pytest.approx(0.99)
    assert v.efectivo == pytest.approx(990 - 0.99)
    assert v.costo_deslizamiento == pytest.approx(10)


def test_cuentas_a_mano():
    serie = serie_backtest(APERTURAS, CIERRES)
    # La señal de comprar sale al cierre de la vela 0; la de vender, al cierre de la vela 2.
    objetivo = np.array([1, 1, 0, 0, 0], dtype=np.int8)
    r = simular(serie, objetivo, costos=SIN_DESLIZAMIENTO)

    cantidad = 999 / 110  # compra en la APERTURA de la vela 1, paga 1 USDT de comisión
    recibido = cantidad * 130 * 0.999  # venta en la apertura de la vela 3
    assert [e.lado for e in r.ejecuciones] == ["compra", "venta"]
    assert [e.ts for e in r.ejecuciones] == [T0 + UNA_HORA, T0 + 3 * UNA_HORA]
    assert r.capital == pytest.approx([1000, cantidad * 115, cantidad * 125, recibido, recibido])
    m = r.metricas
    assert m.capital_final == pytest.approx(recibido)
    assert m.rendimiento == pytest.approx(recibido / 1000 - 1)
    assert m.operaciones == 1
    assert m.comisiones == pytest.approx(1 + cantidad * 130 * 0.001)
    assert m.ganadoras == 1.0
    assert m.exposicion == pytest.approx(2 / 5)
    assert m.drawdown_maximo == 0.0


def test_drawdown():
    serie = serie_backtest([100, 100, 100, 100], [100, 120, 90, 130])
    r = simular(serie, np.array([1, 1, 1, 1], dtype=np.int8), costos=Costos(0, 0), objetivo_previo=1)
    assert r.drawdown == pytest.approx([0, 0, 90 / 120 - 1, 0])
    assert r.metricas.drawdown_maximo == pytest.approx(-0.25)


def test_vela_sin_operaciones_retrasa_la_orden():
    # La vela 1 no tuvo operaciones: la compra espera a la apertura de la vela 2.
    serie = serie_backtest(APERTURAS, CIERRES, operaciones=[10, 0, 10, 10, 10])
    r = simular(serie, np.array([1, 1, 1, 0, 0], dtype=np.int8), costos=SIN_DESLIZAMIENTO)
    assert r.ejecuciones[0].ts == T0 + 2 * UNA_HORA
    assert r.ejecuciones[0].precio_mercado == 120


def test_orden_que_se_cancela_antes_de_ejecutarse():
    # Señal de compra al cierre de la vela 0, pero al cierre de la vela 1 ya es de venta;
    # como la vela 1 no tuvo operaciones, nunca se llega a comprar.
    serie = serie_backtest(APERTURAS, CIERRES, operaciones=[10, 0, 10, 10, 10])
    r = simular(serie, np.array([1, 0, 0, 0, 0], dtype=np.int8), costos=SIN_DESLIZAMIENTO)
    assert r.ejecuciones == []
    assert r.metricas.rendimiento == 0


def test_cierre_forzoso_al_final():
    serie = serie_backtest(APERTURAS, CIERRES)
    r = simular(serie, np.ones(5, dtype=np.int8), costos=SIN_DESLIZAMIENTO)
    ultima = r.ejecuciones[-1]
    assert (ultima.lado, ultima.motivo, ultima.precio_mercado) == ("venta", "fin de ventana", 145)
    assert r.metricas.operaciones == 1
    assert r.capital[-1] == pytest.approx(999 / 110 * 145 * 0.999)


def test_ventana_usa_la_senal_de_la_vela_anterior():
    serie = serie_backtest(APERTURAS, CIERRES)
    objetivo = np.array([0, 1, 1, 1, 1], dtype=np.int8)
    r = simular(serie, objetivo, inicio=2, costos=SIN_DESLIZAMIENTO)
    # La señal de la vela 1 (antes de la ventana) se ejecuta al abrir la vela 2.
    assert r.ejecuciones[0].ts == T0 + 2 * UNA_HORA
    assert len(r.capital) == 3


def test_fraccion_invierte_solo_una_parte():
    serie = serie_backtest(APERTURAS, CIERRES)
    r = simular(serie, np.array([1, 1, 0, 0, 0], dtype=np.int8), costos=SIN_DESLIZAMIENTO, fraccion=0.5)
    cantidad = 499.5 / 110
    assert r.capital[1] == pytest.approx(500 + cantidad * 115)


def test_comprar_y_mantener():
    serie = serie_backtest(APERTURAS, CIERRES)
    costos = Costos(comision=0.001, deslizamiento=0.01)
    r = comprar_y_mantener(serie, costos=costos)
    cantidad = 999 / 101  # compra al abrir la primera vela, con deslizamiento
    final = cantidad * 145 * 0.99 * 0.999  # vende al cierre de la última
    assert r.ejecuciones[0].ts == T0
    assert r.metricas.capital_final == pytest.approx(final)
    assert r.metricas.operaciones == 1


def test_no_operar():
    m = no_operar(1000)
    assert (m.capital_final, m.rendimiento, m.drawdown_maximo, m.operaciones, m.comisiones) == (1000, 0, 0, 0, 0)


def test_backtest_compara_con_las_dos_referencias():
    serie = caminata(500)
    c = backtest(serie, estrategias.obtener("cruce_medias"), {"rapida": 5, "lenta": 20})
    assert c.no_operar.rendimiento == 0
    assert c.comprar_y_mantener.metricas.operaciones == 1
    assert c.le_gana_a_ambas == (
        c.estrategia.metricas.rendimiento > 0
        and c.estrategia.metricas.rendimiento > c.comprar_y_mantener.metricas.rendimiento
    )


def test_costos_mas_altos_nunca_mejoran_el_resultado():
    serie = caminata(800, semilla=3)
    e = estrategias.obtener("momentum")
    baratos = backtest(serie, e, {"ventana": 3}, costos=Costos(0.0, 0.0)).estrategia.metricas
    caros = backtest(serie, e, {"ventana": 3}, costos=Costos(0.001, 0.0005)).estrategia.metricas
    assert caros.operaciones == baratos.operaciones
    assert caros.capital_final < baratos.capital_final


@pytest.mark.parametrize("nombre", list(estrategias.ESTRATEGIAS))
def test_estrategias_no_ven_el_futuro(nombre):
    # La señal de cada vela no puede cambiar si se alteran o se quitan las velas posteriores.
    e = estrategias.obtener(nombre)
    parametros = {p.nombre: p.rejilla[0] for p in e.parametros}
    if nombre == "cruce_medias":
        parametros = {"rapida": 5, "lenta": 20}
    serie = caminata(600, semilla=7)
    if e.factores:  # columnas de factores simuladas, ya alineadas como las deja cargar_serie
        rng = np.random.default_rng(1)
        serie.velas["funding_3d"] = rng.normal(0.0002, 0.0002, len(serie))
        serie.velas["miedo_codicia"] = rng.integers(0, 100, len(serie)).astype(float)
    completo = e.objetivo(serie.velas, parametros)
    corte = 400
    truncada = e.objetivo(serie.velas.iloc[:corte].copy(), parametros)
    assert np.array_equal(completo[:corte], truncada)

    alterada = serie.velas.copy()
    alterada.loc[corte:, ["apertura", "maximo", "minimo", "cierre"]] *= 3
    assert np.array_equal(e.objetivo(alterada, parametros)[:corte], completo[:corte])


def test_validacion_de_parametros():
    e = estrategias.obtener("cruce_medias")
    assert e.completar({}) == {"rapida": 20, "lenta": 50}
    assert e.completar({"rapida": "10"}) == {"rapida": 10, "lenta": 50}
    with pytest.raises(ValueError, match="más corta"):
        e.completar({"rapida": 50, "lenta": 20})
    with pytest.raises(ValueError, match="no tiene"):
        e.completar({"rapido": 5})
    with pytest.raises(ValueError, match="entero"):
        e.completar({"rapida": 2.5})
    with pytest.raises(ValueError):
        estrategias.obtener("no_existe")


def test_rejillas():
    assert len(estrategias.obtener("cruce_medias").rejilla()) == 13
    assert all(p["rapida"] < p["lenta"] for p in estrategias.obtener("cruce_medias").rejilla())
    assert len(estrategias.obtener("ruptura").rejilla()) == 12
    assert len(estrategias.obtener("rsi").rejilla()) == 12
    assert len(estrategias.obtener("momentum").rejilla()) == 6


def test_estrategia_con_factores_exige_sus_columnas():
    serie = caminata(300)
    e = estrategias.obtener("momentum_apalancamiento")
    with pytest.raises(ValueError, match="factores"):
        e.objetivo(serie.velas, {})
    serie.velas["funding_3d"] = 0.001  # funding muy alto todo el tiempo: nunca entra
    assert e.objetivo(serie.velas, {"ventana": 5, "umbral": 0.0003}).sum() == 0
    serie.velas["funding_3d"] = np.nan  # sin datos del factor: igual que momentum
    igual = estrategias.obtener("momentum").objetivo(serie.velas, {"ventana": 5})
    assert np.array_equal(e.objetivo(serie.velas, {"ventana": 5, "umbral": 0.0003}), igual)


# --- Posiciones parciales y métricas de riesgo ---------------------------------------------------

from tradinglab.backtest.motor import anualizar  # noqa: E402


def test_fraccional_con_todo_invertido_es_igual_que_todo_o_nada():
    serie = caminata(400, semilla=5)
    costos = Costos(0.001, 0.0005)
    binario = comprar_y_mantener(serie, 10, 390, costos)
    unos = np.ones(len(serie))
    parcial = simular(serie, unos, 10, 390, costos, objetivo_previo=1.0, fraccional=True)
    assert parcial.capital == pytest.approx(binario.capital)
    assert parcial.metricas.comisiones == pytest.approx(binario.metricas.comisiones)
    assert parcial.metricas.operaciones == binario.metricas.operaciones == 1


def test_fraccional_cuentas_a_mano():
    serie = serie_backtest([100, 100, 100, 200, 200], [100, 100, 100, 200, 200])
    # Mitad invertida desde la vela 1; la señal de bajar a 20% sale al cierre de la vela 3.
    objetivo = np.array([0.5, 0.5, 0.5, 0.2, 0.2])
    r = simular(serie, objetivo, costos=Costos(0.001, 0.0))
    cantidad = 500 * 0.999 / 100  # compra en la apertura de la vela 1 con la mitad del capital
    assert r.ejecuciones[0].ts == T0 + UNA_HORA and r.ejecuciones[0].cantidad == pytest.approx(cantidad)
    assert r.capital[1] == pytest.approx(500 + cantidad * 100)

    # Vela 3: el precio se duplicó y lo invertido pasó de 50% a 67%; más de 10 puntos de
    # diferencia, así que rebalancea de vuelta a 50%.
    valor = 500 + cantidad * 200
    vendida = (cantidad * 200 / valor - 0.5) * valor / 200
    rebalanceo = r.ejecuciones[1]
    assert (rebalanceo.lado, rebalanceo.ts) == ("venta", T0 + 3 * UNA_HORA)
    assert rebalanceo.cantidad == pytest.approx(vendida)
    op = r.operaciones[0]
    assert op.invertido == pytest.approx(500 * vendida / cantidad)  # costo promedio de lo vendido
    assert op.ganancia > 0

    # Vela 4: baja a 20%. Al final se vende el resto.
    assert [(e.lado, e.motivo) for e in r.ejecuciones[2:]] == [("venta", "señal"), ("venta", "fin de ventana")]
    assert r.ejecuciones[2].ts == T0 + 4 * UNA_HORA
    assert r.metricas.operaciones == 3


def test_banda_evita_ajustes_chicos():
    serie = caminata(200, semilla=2)
    pequenos = np.where(np.arange(200) % 2 == 0, 0.50, 0.55)  # oscila 5 puntos: no rebalancea
    r = simular(serie, pequenos, costos=Costos(0.001, 0.0))
    assert [e.lado for e in r.ejecuciones] == ["compra", "venta"]  # entrar y la venta final
    grandes = np.where(np.arange(200) < 100, 0.5, 0.8)  # sube 30 puntos: sí rebalancea
    r = simular(serie, grandes, costos=Costos(0.001, 0.0))
    assert [e.lado for e in r.ejecuciones] == ["compra", "compra", "venta"]
    assert r.metricas.exposicion == pytest.approx(0.65, abs=0.05)  # promedio de lo invertido


def test_salir_del_todo_siempre_se_ejecuta():
    serie = caminata(50, semilla=4)
    objetivo = np.where(np.arange(50) < 20, 0.05, 0.0)  # 5%: menos que la banda, pero salir es salir
    objetivo[:10] = 0.5
    r = simular(serie, objetivo, costos=Costos(0.001, 0.0))
    assert [e.lado for e in r.ejecuciones] == ["compra", "venta", "venta"]
    assert r.ejecuciones[-1].motivo == "señal"


def test_rendimiento_anual_y_calmar():
    assert anualizar(1.0, 730) == pytest.approx(2**0.5 - 1)
    assert anualizar(-1.0, 100) == -1
    serie = serie_backtest([100] * 48, [100 + i for i in range(48)])  # 2 días de velas de 1h
    r = comprar_y_mantener(serie, costos=Costos(0, 0))
    assert r.metricas.rendimiento_anual == pytest.approx(anualizar(r.metricas.rendimiento, 2.0))
    assert r.metricas.calmar is None or r.metricas.calmar > 0


def test_estrategias_de_riesgo():
    serie = caminata(3000, semilla=8)
    vol = estrategias.obtener("volatilidad_objetivo")
    pesos = vol.objetivo(serie.velas, {"ventana": 168, "vol_objetivo": 0.2})
    assert pesos.dtype == np.float64 and 0 <= pesos.min() and pesos.max() <= 1
    # Caminata con 1% por hora ~ 94% anual: con objetivo de 20% invierte cerca de una quinta parte.
    assert np.nanmedian(pesos[200:]) == pytest.approx(0.2 / (0.01 * np.sqrt(8760)), rel=0.15)
    tendencia = estrategias.obtener("tendencia_larga").objetivo(serie.velas, {"ventana": 100})
    assert set(np.unique(tendencia)) <= {0, 1}
    combinada = estrategias.obtener("tendencia_volatilidad").objetivo(
        serie.velas, {"ventana_tendencia": 100, "ventana_vol": 168, "vol_objetivo": 0.2})
    assert np.all(combinada[tendencia == 0] == 0)  # fuera de tendencia, nada invertido
