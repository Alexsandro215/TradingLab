"""Cliente de la API REST pública de Binance.

Solo usa endpoints públicos de datos de mercado: no necesita llaves y no puede enviar
órdenes. Respeta los límites de peso de Binance y reintenta los errores temporales.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Sequence

import requests

log = logging.getLogger(__name__)

URLS_POR_DEFECTO = ("https://api.binance.com", "https://data-api.binance.vision")
MAX_VELAS_POR_PETICION = 1000
LIMITE_PESO_MINUTO = 6000
# Si el peso usado en el minuto pasa de esta fracción del límite, se espera al minuto siguiente.
FRACCION_PESO_MAXIMA = 0.8


class ErrorBinance(RuntimeError):
    """Error al consultar Binance que no se resolvió con reintentos."""


class IPBloqueada(ErrorBinance):
    """Binance bloqueó la IP (HTTP 418) por exceder sus límites. Hay que detenerse."""


class ClienteBinance:
    """Cliente mínimo de datos de mercado de Binance spot."""

    def __init__(
        self,
        urls: Sequence[str] = URLS_POR_DEFECTO,
        pausa: float = 0.1,
        reintentos: int = 6,
        timeout: float = 30.0,
        sesion: requests.Session | None = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
        reloj_pared: Callable[[], float] = time.time,
        limite_peso: int = LIMITE_PESO_MINUTO,
    ) -> None:
        if not urls:
            raise ValueError("Se necesita al menos una URL de Binance")
        self.urls = [url.rstrip("/") for url in urls]
        self._indice_url = 0
        self.pausa = pausa
        self.reintentos = reintentos
        self.timeout = timeout
        self.sesion = sesion if sesion is not None else requests.Session()
        self._dormir = dormir
        self._reloj = reloj
        self._reloj_pared = reloj_pared
        self._ultima_peticion: float | None = None
        self.peticiones = 0
        # Spot permite 6000 de peso por minuto; futuros (fapi), 2400.
        self.limite_peso = limite_peso

    @property
    def url_actual(self) -> str:
        return self.urls[self._indice_url]

    def hora_servidor(self) -> int:
        """Hora del servidor de Binance, en ms desde epoch."""
        return int(self._get("/api/v3/time")["serverTime"])

    def velas(
        self,
        simbolo: str,
        intervalo: str,
        inicio_ms: int,
        limite: int = MAX_VELAS_POR_PETICION,
    ) -> list[list[Any]]:
        """Hasta `limite` velas desde `inicio_ms` (inclusive), de la más antigua a la más nueva.

        Cada vela es la lista de 12 campos que devuelve Binance. La última puede seguir
        abierta (todavía formándose).
        """
        parametros = {
            "symbol": simbolo,
            "interval": intervalo,
            "startTime": inicio_ms,
            "limit": limite,
        }
        return self._get("/api/v3/klines", parametros)

    def get(self, ruta: str, parametros: dict[str, Any] | None = None) -> Any:
        """GET a cualquier endpoint público, con los mismos reintentos y límites."""
        return self._get(ruta, parametros)

    # --- interno ---------------------------------------------------------------------

    def _get(self, ruta: str, parametros: dict[str, Any] | None = None) -> Any:
        fallos = 0
        while True:
            self._esperar_turno()
            url = self.url_actual + ruta
            self._ultima_peticion = self._reloj()
            self.peticiones += 1
            try:
                respuesta = self.sesion.get(url, params=parametros, timeout=self.timeout)
            except requests.RequestException as error:
                fallos += 1
                self._fallo_temporal(fallos, f"error de red: {error}", cambiar_url=True)
                continue

            codigo = respuesta.status_code
            if codigo == 200:
                try:
                    datos = respuesta.json()
                except ValueError:
                    fallos += 1
                    self._fallo_temporal(fallos, "respuesta que no es JSON", cambiar_url=False)
                    continue
                self._controlar_peso(respuesta)
                return datos

            if codigo == 418:
                raise IPBloqueada(
                    "Binance bloqueó la IP por exceso de peticiones (HTTP 418). "
                    f"Hay que esperar antes de volver a intentar. {respuesta.text[:200]}"
                )
            if codigo == 429:
                fallos += 1
                if fallos > self.reintentos:
                    raise ErrorBinance("Binance sigue pidiendo esperar (HTTP 429); se agotaron los reintentos")
                espera = _segundos(respuesta.headers.get("Retry-After"), por_defecto=60.0)
                log.warning("Binance pide esperar %.0f s (HTTP 429)", espera)
                self._dormir(espera)
                continue
            if codigo in (403, 451) or codigo >= 500:
                # 403/451: bloqueo del sitio o por región; se prueba la URL de respaldo.
                fallos += 1
                self._fallo_temporal(fallos, f"HTTP {codigo}", cambiar_url=codigo in (403, 451))
                continue

            raise ErrorBinance(f"HTTP {codigo} en {ruta} {parametros or ''}: {respuesta.text[:300]}")

    def _esperar_turno(self) -> None:
        if self._ultima_peticion is None or self.pausa <= 0:
            return
        transcurrido = self._reloj() - self._ultima_peticion
        if transcurrido < self.pausa:
            self._dormir(self.pausa - transcurrido)

    def _fallo_temporal(self, fallos: int, motivo: str, cambiar_url: bool) -> None:
        if fallos > self.reintentos:
            raise ErrorBinance(f"Se agotaron los reintentos contra Binance (último fallo: {motivo})")
        espera = float(min(2**fallos, 60))
        log.warning(
            "Falló la petición a %s (%s). Reintento %d de %d en %.0f s",
            self.url_actual,
            motivo,
            fallos,
            self.reintentos,
            espera,
        )
        if cambiar_url and len(self.urls) > 1:
            self._indice_url = (self._indice_url + 1) % len(self.urls)
            log.warning("Se usará %s", self.url_actual)
        self._dormir(espera)

    def _controlar_peso(self, respuesta: requests.Response) -> None:
        usado = _segundos(respuesta.headers.get("X-MBX-USED-WEIGHT-1M"), por_defecto=0.0)
        if usado >= self.limite_peso * FRACCION_PESO_MAXIMA:
            espera = 61.0 - self._reloj_pared() % 60
            log.warning("Peso usado %.0f de %d en este minuto; esperando %.0f s", usado, self.limite_peso, espera)
            self._dormir(espera)


def _segundos(valor: str | None, por_defecto: float) -> float:
    try:
        return float(valor) if valor is not None else por_defecto
    except ValueError:
        return por_defecto
