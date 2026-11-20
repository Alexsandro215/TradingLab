"""Operador de papel: las reglas del backtest aplicadas a velas que llegan en vivo.

- Al CIERRE de cada vela se guarda la vela y se calcula la posición objetivo con la estrategia.
- La orden se ejecuta en la APERTURA de la vela siguiente, en cuanto esa vela tiene alguna
  operación (igual que el motor: en una vela sin operaciones no hubo precio real).
- Excepción honesta: si el programa se conecta (o reconecta) a mitad de una vela, no conoce
  el precio de apertura "a tiempo"; ahí ejecuta al precio actual, sin aprovechar el pasado.
- Mismos costos que el backtest (comisión y deslizamiento) y misma estrategia.
- Todo se guarda en SQLite después de cada cambio: si el programa se cierra, la sesión sigue
  donde se quedó.

No envía órdenes a ningún exchange: solo escribe en la base local.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradinglab import db
from tradinglab.backtest.costos import Costos, comprar, vender
from tradinglab.backtest.datos import COLUMNAS
from tradinglab.backtest.estrategias import obtener, texto_parametros
from tradinglab.tiempo import duracion_ms, ms_a_texto

log = logging.getLogger(__name__)

# Velas de historia con que se calcula la señal (suficiente para las medias más largas y el RSI).
HISTORIA_MINIMA = 1000


@dataclass(frozen=True)
class ConfigSesion:
    nombre: str
    simbolo: str
    intervalo: str
    estrategia: str
    parametros: dict[str, Any]
    capital_inicial: float
    fraccion: float
    costos: Costos

    def misma_configuracion(self, otra: "ConfigSesion") -> bool:
        return (
            (self.simbolo, self.intervalo, self.estrategia, texto_parametros(self.parametros),
             self.capital_inicial, self.fraccion, self.costos)
            == (otra.simbolo, otra.intervalo, otra.estrategia, texto_parametros(otra.parametros),
                otra.capital_inicial, otra.fraccion, otra.costos)
        )


def historia_necesaria(sesion: ConfigSesion) -> int:
    parametros = obtener(sesion.estrategia).completar(sesion.parametros)
    mayor = max([int(v) for v in parametros.values() if isinstance(v, int)] or [1])
    return max(HISTORIA_MINIMA, 5 * mayor)


def leer_sesion(con: sqlite3.Connection, nombre: str) -> ConfigSesion | None:
    fila = con.execute(
        "SELECT nombre, simbolo, intervalo, estrategia, parametros, capital_inicial, fraccion, comision, "
        "deslizamiento FROM papel_sesiones WHERE nombre = ?",
        (nombre,),
    ).fetchone()
    if fila is None:
        return None
    return ConfigSesion(fila[0], fila[1], fila[2], fila[3], json.loads(fila[4]), fila[5], fila[6], Costos(fila[7], fila[8]))


def borrar_sesion(con: sqlite3.Connection, nombre: str) -> None:
    with con:
        con.execute("DELETE FROM papel_capital WHERE sesion = ?", (nombre,))
        con.execute("DELETE FROM papel_operaciones WHERE sesion = ?", (nombre,))
        con.execute("DELETE FROM papel_sesiones WHERE nombre = ?", (nombre,))


def resumen_sesion(con: sqlite3.Connection, nombre: str) -> dict[str, Any] | None:
    """Estado de la sesión comparado con no operar y con comprar y mantener desde que empezó."""
    con.row_factory = sqlite3.Row
    try:
        fila = con.execute("SELECT * FROM papel_sesiones WHERE nombre = ?", (nombre,)).fetchone()
        if fila is None:
            return None
        s = dict(fila)
        inicio = con.execute(
            "SELECT v.cierre FROM papel_capital c JOIN velas v ON v.simbolo = ? AND v.intervalo = ? AND v.ts = c.ts "
            "WHERE c.sesion = ? ORDER BY c.ts LIMIT 1",
            (s["simbolo"], s["intervalo"], nombre),
        ).fetchone()
        s["operaciones"] = con.execute(
            "SELECT COUNT(*) FROM papel_operaciones WHERE sesion = ? AND lado = 'venta'", (nombre,)
        ).fetchone()[0]
    finally:
        con.row_factory = None
    s["parametros"] = json.loads(s["parametros"])
    precio = s["ultimo_precio"] or 0.0
    s["capital"] = s["efectivo"] + s["cantidad"] * precio
    s["rendimiento"] = s["capital"] / s["capital_inicial"] - 1
    s["bh_rendimiento"] = None
    if inicio and precio:
        costos = Costos(s["comision"], s["deslizamiento"])
        compra = comprar(s["capital_inicial"], inicio[0], costos)
        s["bh_rendimiento"] = vender(compra.cantidad, precio, costos).efectivo / s["capital_inicial"] - 1
    return s


class Operador:
    def __init__(self, con: sqlite3.Connection, sesion: ConfigSesion) -> None:
        self.con = con
        self.sesion = sesion
        self.estrategia = obtener(sesion.estrategia)
        if self.estrategia.factores:
            raise ValueError(f"La estrategia {sesion.estrategia} usa factores externos "
                             f"({', '.join(self.estrategia.factores)}), y la operación en papel todavía no "
                             "los recibe en vivo.")
        self.parametros = self.estrategia.completar(sesion.parametros)
        self.duracion = duracion_ms(sesion.intervalo)
        self.historia = historia_necesaria(sesion)
        self.ultima_cerrada_ts: int | None = db.ultima_ts(con, sesion.simbolo, sesion.intervalo)
        # Vela en curso cuando se conectó: su apertura ya pasó, no se puede usar.
        self.vela_tardia_ts: int | None = None
        self.ultimo_precio: float | None = None

        fila = con.execute(
            "SELECT efectivo, cantidad, objetivo, precio_entrada, ultimo_precio FROM papel_sesiones WHERE nombre = ?",
            (sesion.nombre,),
        ).fetchone()
        if fila is None:
            self._crear()
        else:
            self.efectivo, self.cantidad, self.objetivo, self.precio_entrada, self.ultimo_precio = fila

    # --- Estado ------------------------------------------------------------------------------

    def _crear(self) -> None:
        s = self.sesion
        ahora = int(time.time() * 1000)
        self.efectivo, self.cantidad, self.objetivo, self.precio_entrada = s.capital_inicial, 0.0, 0, None
        with self.con:
            self.con.execute(
                "INSERT INTO papel_sesiones (nombre, creada_ms, simbolo, intervalo, estrategia, parametros, "
                "capital_inicial, fraccion, comision, deslizamiento, efectivo, cantidad, objetivo, actualizada_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
                (s.nombre, ahora, s.simbolo, s.intervalo, s.estrategia, texto_parametros(self.parametros),
                 s.capital_inicial, s.fraccion, s.costos.comision, s.costos.deslizamiento, s.capital_inicial, ahora),
            )
            # Punto de partida de la curva (y precio de referencia para comprar y mantener).
            if self.ultima_cerrada_ts is not None:
                self.con.execute(
                    "INSERT OR REPLACE INTO papel_capital (sesion, ts, capital) VALUES (?, ?, ?)",
                    (s.nombre, self.ultima_cerrada_ts, s.capital_inicial),
                )
        log.info("Sesión nueva %r con %.2f USDT", s.nombre, s.capital_inicial)

    def _guardar(self) -> None:
        self.con.execute(
            "UPDATE papel_sesiones SET efectivo = ?, cantidad = ?, objetivo = ?, precio_entrada = ?, "
            "ultimo_precio = ?, actualizada_ms = ? WHERE nombre = ?",
            (self.efectivo, self.cantidad, self.objetivo, self.precio_entrada, self.ultimo_precio,
             int(time.time() * 1000), self.sesion.nombre),
        )

    @property
    def capital(self) -> float:
        return self.efectivo + self.cantidad * (self.ultimo_precio or 0.0)

    # --- Señal -------------------------------------------------------------------------------

    def recalcular(self) -> int:
        """Posición objetivo según la última vela cerrada guardada."""
        filas = self.con.execute(
            f"SELECT {', '.join(COLUMNAS)} FROM velas WHERE simbolo = ? AND intervalo = ? ORDER BY ts DESC LIMIT ?",
            (self.sesion.simbolo, self.sesion.intervalo, self.historia),
        ).fetchall()
        if not filas:
            return self.objetivo
        velas = pd.DataFrame(filas[::-1], columns=list(COLUMNAS))
        self.objetivo = int(self.estrategia.objetivo(velas, self.parametros)[-1])
        self.ultima_cerrada_ts = int(velas["ts"].iloc[-1])
        if self.ultimo_precio is None:
            self.ultimo_precio = float(velas["cierre"].iloc[-1])
        with self.con:
            self._guardar()
        return self.objetivo

    # --- Eventos del websocket ---------------------------------------------------------------

    def al_conectar(self) -> None:
        """Se llama en cada (re)conexión: la vela en curso ya empezó sin nosotros."""
        self.vela_tardia_ts = None
        self._primer_mensaje = True

    def procesar_kline(self, k: dict[str, Any]) -> None:
        """Mensaje de vela del websocket de Binance (el objeto 'k' del evento kline)."""
        ts = int(k["t"])
        if getattr(self, "_primer_mensaje", False):
            self._primer_mensaje = False
            if not k["x"]:
                self.vela_tardia_ts = ts
        if k["x"]:
            fila = (self.sesion.simbolo, self.sesion.intervalo, ts, float(k["o"]), float(k["h"]), float(k["l"]),
                    float(k["c"]), float(k["v"]), float(k["q"]), int(k["n"]), float(k["V"]), float(k["Q"]))
            self.al_cerrar_vela(fila)
        else:
            self.al_actualizar_vela(ts, float(k["o"]), float(k["c"]), int(k["n"]))

    def al_actualizar_vela(self, ts: int, apertura: float, precio: float, operaciones: int) -> None:
        """Vela en curso: ejecuta la orden pendiente en su apertura (si ya hubo operaciones)."""
        self.ultimo_precio = precio
        if operaciones <= 0 or self.ultima_cerrada_ts is None or ts <= self.ultima_cerrada_ts:
            return
        quiere_entrar = self.objetivo == 1 and self.cantidad == 0
        quiere_salir = self.objetivo == 0 and self.cantidad > 0
        if not (quiere_entrar or quiere_salir):
            return
        tardia = ts == self.vela_tardia_ts
        precio_mercado = precio if tardia else apertura
        if quiere_entrar:
            invertido = self.efectivo * self.sesion.fraccion
            fill = comprar(invertido, precio_mercado, self.sesion.costos)
            self.efectivo -= invertido
            self.cantidad = fill.cantidad
            self.precio_entrada = invertido / fill.cantidad
            lado = "compra"
        else:
            fill = vender(self.cantidad, precio_mercado, self.sesion.costos)
            self.efectivo += fill.efectivo
            self.cantidad = 0.0
            self.precio_entrada = None
            lado = "venta"
        with self.con:
            self.con.execute(
                "INSERT INTO papel_operaciones (sesion, ts, lado, precio, cantidad, comision, efectivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.sesion.nombre, ts, lado, fill.precio, fill.cantidad, fill.comision, self.efectivo),
            )
            self._guardar()
        momento = "precio actual (conexión a mitad de vela)" if tardia else "apertura"
        log.info("%s %s: %s %.6f a %.4f (%s), comisión %.4f. Efectivo %.2f USDT",
                 self.sesion.nombre, ms_a_texto(ts), lado.upper(), fill.cantidad, fill.precio, momento,
                 fill.comision, self.efectivo)

    def al_cerrar_vela(self, fila: tuple) -> None:
        """Vela cerrada: se guarda, se recalcula la señal y se registra el capital."""
        db.insertar_velas(self.con, [fila])
        ts, cierre = fila[2], fila[6]
        self.ultimo_precio = cierre
        anterior = self.objetivo
        self.recalcular()
        with self.con:
            self.con.execute(
                "INSERT OR REPLACE INTO papel_capital (sesion, ts, capital) VALUES (?, ?, ?)",
                (self.sesion.nombre, ts, self.capital),
            )
        cambio = "" if self.objetivo == anterior else f" -> nueva señal: {'COMPRAR' if self.objetivo else 'VENDER'}"
        log.info("%s %s cerró en %.4f. Capital %.2f USDT, %s%s", self.sesion.nombre, ms_a_texto(ts), cierre,
                 self.capital, "comprado" if self.cantidad > 0 else "fuera", cambio)
