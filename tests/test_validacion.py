import pytest

from tradinglab import db
from tradinglab.backtest.costos import Costos
from tradinglab.config import ConfigCostos
from tradinglab.recolector.descarga import kline_a_fila
from tradinglab.tiempo import fecha_a_ms
from tradinglab.validacion import registro
from tradinglab.validacion.barrido import correr_barrido
from tradinglab.validacion.ventanas import DIA_MS, pliegues_walk_forward, sumar_meses, ventanas_estandar
from tradinglab.validacion.walk_forward import correr_walk_forward, mensual

from fabrica import UNA_HORA, kline


def test_sumar_meses_respeta_fin_de_mes():
    from datetime import datetime, timezone

    assert sumar_meses(datetime(2020, 1, 31, tzinfo=timezone.utc), 1).day == 29  # 2020 es bisiesto
    assert sumar_meses(datetime(2020, 11, 15, tzinfo=timezone.utc), 3) == datetime(2021, 2, 15, tzinfo=timezone.utc)


def test_ventanas_estandar():
    primera, fin = fecha_a_ms("2020-01-01"), fecha_a_ms("2022-06-15")
    ventanas = ventanas_estandar(["completa", "anual", "hasta_hoy"], primera, fin)
    nombres = [v.nombre for v in ventanas]
    assert nombres == ["completa", "2020", "2021", "2022 (parcial)", "2021 a hoy", "2022 a hoy"]
    v2021 = ventanas[2]
    assert (v2021.desde_ms, v2021.hasta_ms) == (fecha_a_ms("2021-01-01"), fecha_a_ms("2022-01-01"))
    assert ventanas[3].hasta_ms == fin


def test_ventanas_semestrales_y_tipo_invalido():
    ventanas = ventanas_estandar(["semestral"], fecha_a_ms("2020-01-01"), fecha_a_ms("2021-01-01"))
    assert [v.nombre for v in ventanas] == ["2020-S1", "2020-S2"]
    with pytest.raises(ValueError):
        ventanas_estandar(["mensual"], 0, DIA_MS * 100)


def test_pliegues_no_se_enciman_y_cubren_todo():
    primera, fin = fecha_a_ms("2020-01-01"), fecha_a_ms("2021-08-01")
    pliegues = pliegues_walk_forward(primera, fin, meses_entrenamiento=12, meses_prueba=3)
    assert len(pliegues) == 3  # pruebas: 2021-01, 2021-04, 2021-07 (esta última recortada)
    for (ent, pru), (_, siguiente) in zip(pliegues, pliegues[1:]):
        assert ent.hasta_ms == pru.desde_ms  # la prueba empieza justo donde termina el entrenamiento
        assert pru.hasta_ms == siguiente.desde_ms  # pruebas consecutivas, sin huecos ni encimarse
    assert pliegues[0][0].desde_ms == primera
    assert pliegues[1][0].desde_ms == fecha_a_ms("2020-04-01")  # ventana rodante
    assert pliegues[-1][1].hasta_ms == fin
    anclados = pliegues_walk_forward(primera, fin, 12, 3, anclado=True)
    assert all(ent.desde_ms == primera for ent, _ in anclados)


def test_mensual():
    assert mensual(0.0, 30) == 0
    assert mensual(-1.0, 30) == -1
    assert mensual(1.0, 2 * 30.4375) == pytest.approx(2**0.5 - 1)


def _base_con_serie(simbolo="BTCUSDT", dias=500, semilla=1):
    import numpy as np

    con = db.conectar(":memory:")
    rng = np.random.default_rng(semilla)
    n = dias * 24
    precios = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    t0 = fecha_a_ms("2020-01-01")
    db.insertar_velas(con, [kline_a_fila(simbolo, "1h", kline(t0 + i * UNA_HORA, UNA_HORA, float(p))) for i, p in enumerate(precios)])
    return con


def test_barrido_cuenta_y_resume():
    con = _base_con_serie()
    r = correr_barrido(con, ["BTCUSDT"], ["1h"], ["momentum"], ["completa", "anual"], ConfigCostos(), 1000.0)
    ventanas = {c["ventana"] for c in r.corridas}
    assert ventanas == {"completa", "2020", "2021 (parcial)"}
    assert len(r.corridas) == 6 * 3  # 6 combinaciones x 3 ventanas
    total = r.resumen["total"]
    assert total["corridas"] == 18
    assert total["ganan_a_ambas"] == sum(
        c["rendimiento"] > 0 and c["rendimiento"] > c["bh_rendimiento"] for c in r.corridas
    )
    assert {g["ventana"] for g in r.resumen["por_ventana"]} == ventanas


def test_walk_forward_solo_cuenta_fuera_de_muestra():
    con = _base_con_serie(dias=700)
    r = correr_walk_forward(con, "BTCUSDT", "1h", "cruce_medias", 6, 3, "rendimiento", Costos(), 1000.0)
    res = r.resumen
    assert res["pliegues"] == len(r.pliegues) >= 4
    pruebas = [c for c in r.corridas if c["muestra"] == "prueba"]
    entrenamientos = [c for c in r.corridas if c["muestra"] == "entrenamiento"]
    assert len(pruebas) == res["pliegues"]
    assert len(entrenamientos) == res["pliegues"] * res["combinaciones_por_pliegue"]
    assert res["simulaciones"] == len(r.corridas)

    # La combinación elegida en cada pliegue es la mejor de su entrenamiento.
    for p in r.pliegues:
        del_pliegue = [c for c in entrenamientos if c["ventana"] == p["pliegue"]]
        assert p["rendimiento_entrenamiento"] == max(c["rendimiento"] for c in del_pliegue)

    # El rendimiento fuera de muestra es el encadenado de las pruebas.
    producto = 1.0
    for c in pruebas:
        producto *= 1 + c["rendimiento"]
    assert res["rendimiento"] == pytest.approx(producto - 1)
    assert r.capital[-1] == pytest.approx(1000 * producto)
    assert len(r.ts) == len(r.capital) == len(r.capital_bh)
    # Los periodos de prueba no se enciman con su entrenamiento.
    for p in r.pliegues:
        assert p["entrenamiento_desde_ms"] < p["prueba_desde_ms"]


def test_walk_forward_criterio_invalido():
    con = _base_con_serie(dias=100)
    with pytest.raises(ValueError):
        correr_walk_forward(con, "BTCUSDT", "1h", "momentum", 1, 1, "suerte", Costos(), 1000.0)


def test_registro_guarda_y_lee(monkeypatch):
    monkeypatch.setattr(registro, "version_codigo", lambda: "abc123+cambios")
    con = _base_con_serie(dias=60)
    r = correr_barrido(con, ["BTCUSDT"], ["1h"], ["momentum"], ["completa"], ConfigCostos(), 1000.0)
    estudio_id = registro.guardar_estudio(con, "barrido", "prueba", {"a": 1}, r.corridas, r.resumen,
                                          len(r.corridas), r.datos_hasta_ms)
    estudios = registro.listar_estudios(con)
    assert estudios[0]["id"] == estudio_id
    assert estudios[0]["corridas"] == len(r.corridas)
    assert estudios[0]["commit_git"] == "abc123+cambios"
    e = registro.leer_estudio(con, estudio_id)
    assert e["configuracion"] == {"a": 1}
    assert e["resumen"]["total"]["corridas"] == len(r.corridas)
    corridas = registro.leer_corridas(con, estudio_id)
    assert len(corridas) == len(r.corridas)
    assert isinstance(corridas[0]["parametros"], dict)
    assert registro.leer_estudio(con, 999) is None


def test_version_codigo_del_repositorio():
    version = registro.version_codigo()
    assert version is None or len(version.split("+")[0]) >= 7
