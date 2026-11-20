"""Catálogo de estrategias.

Cada estrategia recibe las velas (todo el historial cargado) y sus parámetros, y devuelve la
posición objetivo de cada vela: 1 = estar comprado, 0 = estar fuera (en USDT).

Reglas:
- La posición objetivo de la vela i solo usa información disponible al CIERRE de la vela i
  (principio 6). El motor la ejecuta en la apertura de la vela siguiente.
- Solo posiciones largas: en spot no se puede vender en corto sin margen.
- Pocos parámetros (principio 4). La rejilla de cada parámetro es lo que prueba el barrido.

Los periodos están en número de velas: 20 velas son 100 minutos en 5m y casi un día en 1h.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Parametro:
    nombre: str
    tipo: type  # int o float
    por_defecto: int | float
    descripcion: str
    rejilla: tuple[int | float, ...]


@dataclass(frozen=True)
class Estrategia:
    nombre: str
    titulo: str
    descripcion: str
    parametros: tuple[Parametro, ...]
    calcular: Callable[[pd.DataFrame, dict[str, Any]], Any] = field(repr=False)
    # Devuelve un mensaje si la combinación no tiene sentido; None si es válida.
    validar: Callable[[dict[str, Any]], str | None] = field(default=lambda p: None, repr=False)
    # Columnas de factores externos que necesita (fase 6). Vacío = solo velas.
    factores: tuple[str, ...] = ()

    def completar(self, parametros: dict[str, Any] | None = None) -> dict[str, Any]:
        """Parámetros con valores por defecto, convertidos a su tipo y validados."""
        dados = dict(parametros or {})
        conocidos = {p.nombre for p in self.parametros}
        sobran = set(dados) - conocidos
        if sobran:
            raise ValueError(
                f"La estrategia {self.nombre} no tiene los parámetros {sorted(sobran)}. "
                f"Tiene: {sorted(conocidos)}"
            )
        completos: dict[str, Any] = {}
        for p in self.parametros:
            crudo = dados.get(p.nombre, p.por_defecto)
            try:
                valor = float(crudo)
            except (TypeError, ValueError):
                valor = float("nan")
            if valor != valor or (p.tipo is int and valor != int(valor)):
                tipo = "número entero" if p.tipo is int else "número"
                raise ValueError(f"{self.nombre}: {p.nombre}={crudo!r} no es un {tipo}")
            valor = p.tipo(valor)
            if p.tipo is int and valor < 1:
                raise ValueError(f"{self.nombre}: {p.nombre} debe ser al menos 1")
            completos[p.nombre] = valor
        error = self.validar(completos)
        if error:
            raise ValueError(f"{self.nombre}: {error}")
        return completos

    def objetivo(self, velas: pd.DataFrame, parametros: dict[str, Any] | None = None) -> np.ndarray:
        """Posición objetivo (0 o 1) de cada vela."""
        completos = self.completar(parametros)
        faltan = [f for f in self.factores if f not in velas.columns]
        if faltan:
            raise ValueError(f"La estrategia {self.nombre} necesita los factores {faltan}: carga la serie "
                             "con cargar_serie(..., con_factores=True) y descarga los factores con "
                             "python -m tradinglab factores")
        senal = pd.Series(self.calcular(velas, completos), index=velas.index, dtype="float64")
        return senal.fillna(0).to_numpy().astype(np.int8)

    def rejilla(self) -> list[dict[str, Any]]:
        """Todas las combinaciones válidas de la rejilla de parámetros."""
        nombres = [p.nombre for p in self.parametros]
        combinaciones = []
        for valores in itertools.product(*(p.rejilla for p in self.parametros)):
            candidato = dict(zip(nombres, valores))
            if self.validar(candidato) is None:
                combinaciones.append(candidato)
        return combinaciones


def texto_parametros(parametros: dict[str, Any]) -> str:
    """Forma canónica (JSON ordenado) para guardar y comparar parámetros."""
    return json.dumps(parametros, sort_keys=True)


def _mantener_estado(entrar: pd.Series, salir: pd.Series) -> pd.Series:
    """1 desde que `entrar` se cumple hasta que `salir` se cumple (entrar tiene prioridad)."""
    estado = np.where(entrar, 1.0, np.where(salir, 0.0, np.nan))
    return pd.Series(estado, index=entrar.index).ffill().fillna(0.0)


# --- Estrategias -------------------------------------------------------------------------


def _cruce_medias(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    cierre = v["cierre"]
    rapida = cierre.rolling(p["rapida"]).mean()
    lenta = cierre.rolling(p["lenta"]).mean()
    return (rapida > lenta).astype(float)


def _ruptura(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    # Techo y piso de las velas ANTERIORES (shift(1)): la vela actual no se compara consigo misma.
    techo = v["maximo"].rolling(p["entrada"]).max().shift(1)
    piso = v["minimo"].rolling(p["salida"]).min().shift(1)
    return _mantener_estado(v["cierre"] > techo, v["cierre"] < piso)


def _rsi(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    cambio = v["cierre"].diff()
    alfa = 1 / p["periodo"]  # suavizado de Wilder
    sube = cambio.clip(lower=0).ewm(alpha=alfa, adjust=False, min_periods=p["periodo"]).mean()
    baja = (-cambio.clip(upper=0)).ewm(alpha=alfa, adjust=False, min_periods=p["periodo"]).mean()
    rsi = 100 - 100 / (1 + sube / baja)
    return _mantener_estado(rsi < p["compra"], rsi > p["venta"])


def _momentum(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    cierre = v["cierre"]
    return (cierre > cierre.shift(p["ventana"])).astype(float)


# Fase 6: momentum con filtros de factores externos. Si falta el dato del factor (antes de que
# exista), el filtro no actúa y la estrategia es igual a momentum.


def _momentum_apalancamiento(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    cierre = v["cierre"]
    sube = cierre > cierre.shift(p["ventana"])
    apalancado = v["funding_3d"] > p["umbral"]  # demasiados largos pagando por mantenerse
    return (sube & ~apalancado).astype(float)


def _momentum_sentimiento(v: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    cierre = v["cierre"]
    sube = cierre > cierre.shift(p["ventana"])
    euforia = v["miedo_codicia"] > p["umbral"]
    return (sube & ~euforia).astype(float)


ESTRATEGIAS: dict[str, Estrategia] = {
    e.nombre: e
    for e in (
        Estrategia(
            nombre="cruce_medias",
            titulo="Cruce de medias",
            descripcion="Comprado mientras la media móvil rápida del cierre está arriba de la lenta.",
            parametros=(
                Parametro("rapida", int, 20, "velas de la media rápida", (5, 10, 20, 50)),
                Parametro("lenta", int, 50, "velas de la media lenta", (20, 50, 100, 200)),
            ),
            calcular=_cruce_medias,
            validar=lambda p: None if p["rapida"] < p["lenta"] else "la media rápida debe ser más corta que la lenta",
        ),
        Estrategia(
            nombre="ruptura",
            titulo="Ruptura de canal",
            descripcion=(
                "Compra cuando el cierre rompe el máximo de las últimas N velas; vende cuando "
                "rompe el mínimo de las últimas M (canal de Donchian)."
            ),
            parametros=(
                Parametro("entrada", int, 20, "velas del máximo a romper para comprar", (20, 55, 100, 200)),
                Parametro("salida", int, 10, "velas del mínimo a romper para vender", (10, 20, 50)),
            ),
            calcular=_ruptura,
        ),
        Estrategia(
            nombre="rsi",
            titulo="Reversión con RSI",
            descripcion="Compra cuando el RSI baja del umbral de compra; vende cuando sube del umbral de venta.",
            parametros=(
                Parametro("periodo", int, 14, "velas del RSI", (7, 14, 28)),
                Parametro("compra", float, 30.0, "comprar con RSI menor a esto", (20.0, 30.0)),
                Parametro("venta", float, 70.0, "vender con RSI mayor a esto", (70.0, 80.0)),
            ),
            calcular=_rsi,
            validar=lambda p: None
            if 0 < p["compra"] < p["venta"] < 100
            else "debe cumplirse 0 < compra < venta < 100",
        ),
        Estrategia(
            nombre="momentum",
            titulo="Momentum",
            descripcion="Comprado mientras el cierre está arriba del cierre de hace N velas.",
            parametros=(
                Parametro("ventana", int, 24, "velas hacia atrás", (12, 24, 72, 168, 336, 720)),
            ),
            calcular=_momentum,
        ),
        Estrategia(
            nombre="momentum_apalancamiento",
            titulo="Momentum con filtro de apalancamiento",
            descripcion=(
                "Momentum, pero fuera del mercado cuando el funding promedio de los últimos 3 días "
                "pasa del umbral: señal de demasiados largos apalancados (riesgo de liquidaciones)."
            ),
            parametros=(
                Parametro("ventana", int, 720, "velas hacia atrás", (168, 720)),
                Parametro("umbral", float, 0.0003, "funding por cobro (8 h) arriba del cual se sale",
                          (0.0002, 0.0004)),
            ),
            calcular=_momentum_apalancamiento,
            factores=("funding_3d",),
        ),
        Estrategia(
            nombre="momentum_sentimiento",
            titulo="Momentum con filtro de sentimiento",
            descripcion="Momentum, pero fuera del mercado cuando el índice de miedo y codicia marca euforia.",
            parametros=(
                Parametro("ventana", int, 720, "velas hacia atrás", (168, 720)),
                Parametro("umbral", float, 80.0, "índice arriba del cual se sale (0 a 100)", (75.0, 85.0)),
            ),
            calcular=_momentum_sentimiento,
            factores=("miedo_codicia",),
        ),
    )
}


def obtener(nombre: str) -> Estrategia:
    try:
        return ESTRATEGIAS[nombre]
    except KeyError:
        raise ValueError(f"No existe la estrategia {nombre!r}. Hay: {', '.join(ESTRATEGIAS)}") from None
