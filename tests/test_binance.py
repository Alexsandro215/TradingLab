import pytest
import requests
from requests.structures import CaseInsensitiveDict

from tradinglab.recolector.binance import ClienteBinance, ErrorBinance, IPBloqueada

URLS = ("https://principal", "https://respaldo")


class RespuestaFalsa:
    def __init__(self, codigo=200, datos=None, encabezados=None, texto=""):
        self.status_code = codigo
        self._datos = datos
        self.headers = CaseInsensitiveDict(encabezados or {})
        self.text = texto

    def json(self):
        return self._datos


class SesionFalsa:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.urls = []
        self.parametros = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        self.parametros.append(params)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def cliente(respuestas, **opciones):
    dormidas = []
    sesion = SesionFalsa(respuestas)
    c = ClienteBinance(urls=URLS, pausa=0, sesion=sesion, dormir=dormidas.append, **opciones)
    return c, sesion, dormidas


def test_pide_velas_con_los_parametros_correctos():
    c, sesion, _ = cliente([RespuestaFalsa(datos=[[1, "2"]])])
    assert c.velas("BTCUSDT", "5m", 123) == [[1, "2"]]
    assert sesion.urls == ["https://principal/api/v3/klines"]
    assert sesion.parametros[0] == {"symbol": "BTCUSDT", "interval": "5m", "startTime": 123, "limit": 1000}


def test_hora_servidor():
    c, _, _ = cliente([RespuestaFalsa(datos={"serverTime": 1700000000000})])
    assert c.hora_servidor() == 1700000000000


def test_429_respeta_retry_after():
    c, _, dormidas = cliente([
        RespuestaFalsa(429, encabezados={"Retry-After": "7"}),
        RespuestaFalsa(datos={"serverTime": 5}),
    ])
    assert c.hora_servidor() == 5
    assert dormidas == [7.0]


def test_418_se_detiene():
    c, _, _ = cliente([RespuestaFalsa(418, texto="baneado")])
    with pytest.raises(IPBloqueada):
        c.hora_servidor()


def test_error_de_red_reintenta_con_el_respaldo():
    c, sesion, dormidas = cliente([
        requests.ConnectionError("sin internet"),
        RespuestaFalsa(datos={"serverTime": 5}),
    ])
    assert c.hora_servidor() == 5
    assert sesion.urls == ["https://principal/api/v3/time", "https://respaldo/api/v3/time"]
    assert dormidas == [2.0]


def test_bloqueo_por_region_usa_el_respaldo():
    c, sesion, _ = cliente([RespuestaFalsa(451), RespuestaFalsa(datos={"serverTime": 5})])
    assert c.hora_servidor() == 5
    assert sesion.urls[1].startswith("https://respaldo")


def test_error_500_reintenta_y_luego_se_rinde():
    c, sesion, dormidas = cliente([RespuestaFalsa(500)] * 4, reintentos=3)
    with pytest.raises(ErrorBinance):
        c.hora_servidor()
    assert len(sesion.urls) == 4
    assert dormidas == [2.0, 4.0, 8.0]


def test_error_400_no_reintenta():
    c, sesion, _ = cliente([RespuestaFalsa(400, texto='{"code":-1121,"msg":"Invalid symbol."}')])
    with pytest.raises(ErrorBinance, match="Invalid symbol"):
        c.velas("NOEXISTE", "5m", 0)
    assert len(sesion.urls) == 1


def test_peso_alto_espera_al_minuto_siguiente():
    c, _, dormidas = cliente(
        [RespuestaFalsa(datos={"serverTime": 5}, encabezados={"x-mbx-used-weight-1m": "5000"})],
        reloj_pared=lambda: 120.5,
    )
    c.hora_servidor()
    assert dormidas == [60.5]


def test_peso_normal_no_espera():
    c, _, dormidas = cliente([RespuestaFalsa(datos={"serverTime": 5}, encabezados={"X-MBX-USED-WEIGHT-1M": "200"})])
    c.hora_servidor()
    assert dormidas == []


def test_pausa_entre_peticiones():
    dormidas = []
    # Primera petición en t=0; la segunda se intenta en t=0.03, así que debe esperar 0.07 s.
    tiempos = iter([0.0, 0.03, 0.1])
    sesion = SesionFalsa([RespuestaFalsa(datos={"serverTime": 1}), RespuestaFalsa(datos={"serverTime": 2})])
    c = ClienteBinance(urls=URLS, pausa=0.1, sesion=sesion, dormir=dormidas.append, reloj=lambda: next(tiempos))
    c.hora_servidor()
    c.hora_servidor()
    assert dormidas == [pytest.approx(0.07)]
