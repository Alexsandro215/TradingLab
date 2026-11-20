import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from tradinglab import db
from tradinglab.config import cargar_config
from tradinglab.recolector.descarga import kline_a_fila
from tradinglab.tiempo import fecha_a_ms
from tradinglab.validacion import registro
from tradinglab.validacion.barrido import correr_barrido
from tradinglab.panel import app as modulo_panel

from fabrica import UNA_HORA, kline


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    import numpy as np

    ruta = tmp_path / "base.sqlite"
    con = db.conectar(ruta)
    rng = np.random.default_rng(5)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 2000)))
    t0 = fecha_a_ms("2024-01-01")
    db.insertar_velas(con, [kline_a_fila("BTCUSDT", "1h", kline(t0 + i * UNA_HORA, UNA_HORA, float(p)))
                            for i, p in enumerate(precios)])
    monkeypatch.setattr(registro, "version_codigo", lambda: "abc1234")
    config = replace(cargar_config(), ruta_base=ruta)
    r = correr_barrido(con, ["BTCUSDT"], ["1h"], ["momentum"], ["completa"], config.costos, 1000.0)
    registro.guardar_estudio(con, "barrido", "prueba", {}, r.corridas, r.resumen, len(r.corridas), r.datos_hasta_ms)
    con.close()
    return TestClient(modulo_panel.crear_app(config))


def test_pagina_y_archivos(cliente):
    assert "TradingLab" in cliente.get("/").text
    assert cliente.get("/static/app.js").status_code == 200
    assert cliente.get("/static/estilo.css").status_code == 200


def test_series_y_estrategias(cliente):
    series = cliente.get("/api/series").json()
    assert series == [{"simbolo": "BTCUSDT", "intervalo": "1h", "velas": 2000,
                       "desde_ms": fecha_a_ms("2024-01-01"), "hasta_ms": fecha_a_ms("2024-01-01") + 1999 * UNA_HORA}]
    nombres = [e["nombre"] for e in cliente.get("/api/estrategias").json()]
    assert "cruce_medias" in nombres


def test_backtest(cliente):
    r = cliente.get("/api/backtest", params={"simbolo": "btc/usdt", "intervalo": "1h", "estrategia": "cruce_medias",
                                             "parametros": json.dumps({"rapida": 5, "lenta": 20})})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["velas"]) == len(d["capital"]) == len(d["drawdown"]) == len(d["capital_bh"]) == 2000
    assert d["velas"][0]["time"] == fecha_a_ms("2024-01-01") // 1000
    assert d["metricas"]["operaciones"] == len(d["operaciones"])
    assert len(d["marcas"]) == 2 * d["metricas"]["operaciones"]
    assert d["referencias"]["no_operar"]["rendimiento"] == 0
    assert d["parametros"] == {"rapida": 5, "lenta": 20}


def test_backtest_con_ventana_y_errores(cliente):
    r = cliente.get("/api/backtest", params={"simbolo": "BTCUSDT", "estrategia": "momentum",
                                             "desde": "2024-02-01", "hasta": "2024-02-11"})
    assert r.status_code == 200
    assert len(r.json()["velas"]) == 240
    assert cliente.get("/api/backtest", params={"simbolo": "BTCUSDT", "estrategia": "nada"}).status_code == 400
    assert cliente.get("/api/backtest", params={"simbolo": "BTCUSDT", "parametros": '{"rapida": 50, "lenta": 5}'}).status_code == 400
    assert cliente.get("/api/backtest", params={"simbolo": "ETHUSDT"}).status_code == 404
    assert cliente.get("/api/backtest", params={"simbolo": "BTCUSDT", "desde": "ayer"}).status_code == 400


def test_limite_de_velas(cliente, monkeypatch):
    monkeypatch.setattr(modulo_panel, "MAX_VELAS", 100)
    r = cliente.get("/api/backtest", params={"simbolo": "BTCUSDT"})
    assert r.status_code == 400
    assert "Acorta" in r.json()["detail"]


def test_estudios(cliente):
    estudios = cliente.get("/api/estudios").json()
    assert len(estudios) == 1 and "resumen" not in estudios[0]
    e = cliente.get(f"/api/estudios/{estudios[0]['id']}").json()
    assert e["tipo"] == "barrido"
    assert len(e["corridas"]) == 6
    assert cliente.get("/api/estudios/999").status_code == 404


def test_papel_vacio(cliente):
    assert cliente.get("/api/papel").json() == []
    assert cliente.get("/api/papel/nada").status_code == 404
