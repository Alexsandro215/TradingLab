"""Formato de texto para la línea de comandos."""

from __future__ import annotations

from typing import Any, Sequence


def pct(valor: float | None, signo: bool = True) -> str:
    if valor is None:
        return "-"
    return f"{valor:+.1%}" if signo and round(valor, 3) != 0 else f"{valor:.1%}"


def usd(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:,.2f}"


def entero(valor: int | None) -> str:
    return "-" if valor is None else f"{valor:,}"


def parametros(p: dict[str, Any]) -> str:
    return " ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in sorted(p.items()))


def tabla(encabezados: Sequence[str], filas: Sequence[Sequence[Any]], izquierda: int | set[int] = 1) -> str:
    """Tabla de texto. Se alinean a la izquierda las primeras `izquierda` columnas (o las de ese
    conjunto de índices); el resto, a la derecha."""
    a_la_izquierda = set(range(izquierda)) if isinstance(izquierda, int) else izquierda
    celdas = [[str(c) for c in encabezados]] + [[str(c) for c in f] for f in filas]
    anchos = [max(len(f[i]) for f in celdas) for i in range(len(encabezados))]
    lineas = []
    for n, fila in enumerate(celdas):
        partes = [c.ljust(anchos[i]) if i in a_la_izquierda else c.rjust(anchos[i]) for i, c in enumerate(fila)]
        lineas.append("  ".join(partes).rstrip())
        if n == 0:
            lineas.append("  ".join("-" * a for a in anchos))
    return "\n".join(lineas)
