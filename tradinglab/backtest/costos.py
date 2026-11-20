"""Modelo de costos de ejecución, compartido por el backtest y la operación en papel.

- Deslizamiento: el precio de ejecución es peor que el de mercado en `deslizamiento`
  (se compra más caro y se vende más barato).
- Comisión: fracción del monto operado, cobrada en USDT.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Costos:
    comision: float = 0.001  # 0.1% por lado: tarifa spot de Binance sin descuentos
    deslizamiento: float = 0.0005  # 0.05% por lado

    def __post_init__(self) -> None:
        if not (0 <= self.comision < 0.1 and 0 <= self.deslizamiento < 0.1):
            raise ValueError(f"Costos fuera de rango: {self}")


@dataclass(frozen=True)
class Fill:
    """Resultado de ejecutar una orden."""

    precio: float  # precio de ejecución, con deslizamiento
    cantidad: float  # moneda base comprada o vendida
    efectivo: float  # USDT: gastado (compra, con comisión) o recibido (venta, neto de comisión)
    comision: float  # USDT
    costo_deslizamiento: float  # USDT perdidos contra el precio de mercado


def comprar(efectivo: float, precio_mercado: float, costos: Costos) -> Fill:
    """Gasta `efectivo` USDT (comisión incluida) en comprar al precio de mercado más deslizamiento."""
    precio = precio_mercado * (1 + costos.deslizamiento)
    comision = efectivo * costos.comision
    cantidad = (efectivo - comision) / precio
    return Fill(precio, cantidad, efectivo, comision, cantidad * (precio - precio_mercado))


def vender(cantidad: float, precio_mercado: float, costos: Costos) -> Fill:
    """Vende `cantidad` al precio de mercado menos deslizamiento; devuelve los USDT netos."""
    precio = precio_mercado * (1 - costos.deslizamiento)
    bruto = cantidad * precio
    comision = bruto * costos.comision
    return Fill(precio, cantidad, bruto - comision, comision, cantidad * (precio_mercado - precio))
