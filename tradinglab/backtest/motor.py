"""Motor de backtest.

Reglas de la simulación (ver los principios en CLAUDE.md):

- Solo posiciones largas. Al entrar se invierte `fraccion` del capital; al salir se vende todo.
- La posición objetivo calculada al cierre de la vela i se ejecuta en la APERTURA de la vela
  i+1: la estrategia nunca opera con un precio que todavía no conocía.
- Si esa vela no tuvo operaciones (Binance la llena con el cierre anterior), la orden espera a
  la siguiente vela con operaciones: ahí no hubo un precio real al cual ejecutar.
- Si hay un hueco en los datos (mantenimiento de Binance), la orden se ejecuta en la primera
  vela después del hueco, como habría pasado en la realidad.
- Cada ejecución paga deslizamiento y comisión (ver costos.py).
- Al final de la ventana se cierra la posición al cierre de la última vela, pagando costos,
  para que el resultado sea comparable con comprar y mantener.
- El capital se valúa al cierre de cada vela; el drawdown se mide sobre esa curva.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tradinglab.backtest.costos import Costos, comprar, vender
from tradinglab.backtest.datos import Serie
from tradinglab.backtest.estrategias import Estrategia


@dataclass(frozen=True)
class Ejecucion:
    ts: int  # apertura de la vela en la que se ejecutó
    lado: str  # 'compra' o 'venta'
    precio_mercado: float
    precio: float  # con deslizamiento
    cantidad: float
    comision: float
    costo_deslizamiento: float
    efectivo: float  # efectivo después de la ejecución
    motivo: str  # 'señal' o 'fin de ventana'


@dataclass(frozen=True)
class Operacion:
    """Una operación completa: compra y su venta."""

    entrada_ts: int
    salida_ts: int
    precio_entrada: float
    precio_salida: float
    cantidad: float
    invertido: float  # USDT gastados, con comisión
    recibido: float  # USDT recibidos, netos de comisión

    @property
    def ganancia(self) -> float:
        return self.recibido - self.invertido

    @property
    def rendimiento(self) -> float:
        return self.recibido / self.invertido - 1


@dataclass(frozen=True)
class Metricas:
    capital_inicial: float
    capital_final: float
    rendimiento: float  # neto, fracción: 0.1 = +10%
    drawdown_maximo: float  # fracción negativa: -0.3 = -30%
    operaciones: int  # operaciones completas (compra + venta)
    comisiones: float  # USDT
    costo_deslizamiento: float  # USDT
    ganadoras: float | None  # fracción de operaciones con ganancia; None si no hubo
    exposicion: float  # fracción de velas con posición abierta

    def como_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Resultado:
    ts: np.ndarray  # ts de cada vela de la ventana
    capital: np.ndarray  # capital al cierre de cada vela
    drawdown: np.ndarray  # caída desde el máximo previo, fracción negativa
    ejecuciones: list[Ejecucion]
    operaciones: list[Operacion]
    metricas: Metricas


def no_operar(capital_inicial: float) -> Metricas:
    """Referencia 1: no hacer nada. El capital se queda igual."""
    return Metricas(capital_inicial, capital_inicial, 0.0, 0.0, 0, 0.0, 0.0, None, 0.0)


def simular(
    serie: Serie,
    objetivo: np.ndarray,
    inicio: int = 0,
    fin: int | None = None,
    costos: Costos = Costos(),
    capital_inicial: float = 1000.0,
    fraccion: float = 1.0,
    objetivo_previo: int | None = None,
) -> Resultado:
    """Simula la estrategia en las velas [inicio, fin) de la serie.

    `objetivo` tiene una posición objetivo (0 o 1) por cada vela de TODA la serie. La que se
    ejecuta en la apertura de la vela `inicio` es objetivo[inicio - 1]: viene de una vela
    anterior a la ventana. `objetivo_previo` la sustituye (lo usa comprar y mantener).
    """
    n = len(serie)
    fin = n if fin is None else fin
    if not 0 <= inicio < fin <= n:
        raise ValueError(f"Ventana inválida: [{inicio}, {fin}) en una serie de {n} velas")
    if len(objetivo) != n:
        raise ValueError("objetivo debe tener una posición por vela de la serie")
    if not 0 < fraccion <= 1:
        raise ValueError("fraccion debe estar entre 0 (excluido) y 1")

    m = fin - inicio
    if objetivo_previo is None:
        objetivo_previo = int(objetivo[inicio - 1]) if inicio > 0 else 0
    # deseado[k]: posición que se quiere tener al abrir la vela inicio + k.
    deseado = np.empty(m, dtype=np.int8)
    deseado[0] = 1 if objetivo_previo else 0
    deseado[1:] = objetivo[inicio : fin - 1] != 0
    con_operaciones = serie.operaciones[inicio:fin] > 0
    puntos_entrada = np.flatnonzero((deseado == 1) & con_operaciones)
    puntos_salida = np.flatnonzero((deseado == 0) & con_operaciones)

    efectivo = float(capital_inicial)
    cantidad = 0.0
    ejecuciones: list[Ejecucion] = []
    operaciones: list[Operacion] = []
    cambios_k: list[int] = []
    cambios_efectivo: list[float] = []
    cambios_cantidad: list[float] = []
    compra_abierta: Ejecucion | None = None
    invertido = 0.0

    k = 0
    while True:
        puntos = puntos_salida if compra_abierta else puntos_entrada
        siguiente = int(np.searchsorted(puntos, k))
        if siguiente >= len(puntos):
            break
        k = int(puntos[siguiente])
        j = inicio + k
        precio_mercado = float(serie.apertura[j])
        ts = int(serie.ts[j])
        if compra_abierta is None:
            invertido = efectivo * fraccion
            fill = comprar(invertido, precio_mercado, costos)
            efectivo -= invertido
            cantidad = fill.cantidad
            compra_abierta = Ejecucion(
                ts, "compra", precio_mercado, fill.precio, fill.cantidad, fill.comision,
                fill.costo_deslizamiento, efectivo, "señal",
            )
            ejecuciones.append(compra_abierta)
        else:
            fill = vender(cantidad, precio_mercado, costos)
            efectivo += fill.efectivo
            ejecuciones.append(Ejecucion(
                ts, "venta", precio_mercado, fill.precio, cantidad, fill.comision,
                fill.costo_deslizamiento, efectivo, "señal",
            ))
            operaciones.append(Operacion(
                compra_abierta.ts, ts, compra_abierta.precio, fill.precio, cantidad, invertido, fill.efectivo,
            ))
            cantidad = 0.0
            compra_abierta = None
        cambios_k.append(k)
        cambios_efectivo.append(efectivo)
        cambios_cantidad.append(cantidad)
        k += 1

    # Efectivo y cantidad al cierre de cada vela: constantes entre ejecuciones.
    efectivo_por_vela = np.full(m, float(capital_inicial))
    cantidad_por_vela = np.zeros(m)
    if cambios_k:
        cual = np.searchsorted(np.array(cambios_k), np.arange(m), side="right") - 1
        hay = cual >= 0
        efectivo_por_vela[hay] = np.array(cambios_efectivo)[cual[hay]]
        cantidad_por_vela[hay] = np.array(cambios_cantidad)[cual[hay]]
    capital = efectivo_por_vela + cantidad_por_vela * serie.cierre[inicio:fin]

    # Cierre forzoso al final de la ventana.
    if compra_abierta is not None:
        j = fin - 1
        precio_mercado = float(serie.cierre[j])
        fill = vender(cantidad, precio_mercado, costos)
        efectivo += fill.efectivo
        ejecuciones.append(Ejecucion(
            int(serie.ts[j]), "venta", precio_mercado, fill.precio, cantidad, fill.comision,
            fill.costo_deslizamiento, efectivo, "fin de ventana",
        ))
        operaciones.append(Operacion(
            compra_abierta.ts, int(serie.ts[j]), compra_abierta.precio, fill.precio, cantidad, invertido, fill.efectivo,
        ))
        capital[-1] = efectivo

    drawdown = capital / np.maximum.accumulate(capital) - 1
    ganadoras = sum(op.ganancia > 0 for op in operaciones) / len(operaciones) if operaciones else None
    metricas = Metricas(
        capital_inicial=float(capital_inicial),
        capital_final=float(capital[-1]),
        rendimiento=float(capital[-1] / capital_inicial - 1),
        drawdown_maximo=float(drawdown.min()),
        operaciones=len(operaciones),
        comisiones=float(sum(e.comision for e in ejecuciones)),
        costo_deslizamiento=float(sum(e.costo_deslizamiento for e in ejecuciones)),
        ganadoras=ganadoras,
        exposicion=float((cantidad_por_vela > 0).mean()),
    )
    return Resultado(serie.ts[inicio:fin].copy(), capital, drawdown, ejecuciones, operaciones, metricas)


def comprar_y_mantener(
    serie: Serie,
    inicio: int = 0,
    fin: int | None = None,
    costos: Costos = Costos(),
    capital_inicial: float = 1000.0,
) -> Resultado:
    """Referencia 2: comprar con todo el capital al abrir la ventana y vender al cerrarla,
    pagando los mismos costos que la estrategia."""
    unos = np.ones(len(serie), dtype=np.int8)
    return simular(serie, unos, inicio, fin, costos, capital_inicial, 1.0, objetivo_previo=1)


@dataclass
class Comparacion:
    """Una estrategia y sus dos referencias en la misma ventana."""

    estrategia: Resultado
    comprar_y_mantener: Resultado
    no_operar: Metricas

    @property
    def le_gana_a_no_operar(self) -> bool:
        return self.estrategia.metricas.rendimiento > self.no_operar.rendimiento

    @property
    def le_gana_a_comprar_y_mantener(self) -> bool:
        return self.estrategia.metricas.rendimiento > self.comprar_y_mantener.metricas.rendimiento

    @property
    def le_gana_a_ambas(self) -> bool:
        return self.le_gana_a_no_operar and self.le_gana_a_comprar_y_mantener


def backtest(
    serie: Serie,
    estrategia: Estrategia,
    parametros: dict[str, Any] | None = None,
    desde_ms: int | None = None,
    hasta_ms: int | None = None,
    costos: Costos = Costos(),
    capital_inicial: float = 1000.0,
    fraccion: float = 1.0,
) -> Comparacion:
    """Corre una estrategia en una ventana y la compara con las dos referencias."""
    inicio, fin = serie.rango(desde_ms, hasta_ms)
    if fin - inicio < 2:
        raise ValueError("La ventana tiene menos de 2 velas")
    objetivo = estrategia.objetivo(serie.velas, parametros)
    return Comparacion(
        simular(serie, objetivo, inicio, fin, costos, capital_inicial, fraccion),
        comprar_y_mantener(serie, inicio, fin, costos, capital_inicial),
        no_operar(capital_inicial),
    )
