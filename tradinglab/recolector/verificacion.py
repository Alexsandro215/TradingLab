"""Control de calidad de las velas guardadas.

- Resumen por serie: primera y última vela, total, huecos y velas con valores imposibles.
- Cruce entre intervalos: se juntan las velas finas (p. ej. 12 de 5m) y se comparan con la
  vela gruesa que publica Binance (p. ej. 1h). Deben coincidir.

Ojo con las velas sin operaciones (`operaciones = 0`): Binance las llena con el cierre de la
vela anterior, pero esos precios no cuentan para la vela gruesa, que solo usa precios donde
hubo operaciones. Por eso, al juntar, se ignoran (salvo que ninguna vela del bloque tenga
operaciones). Son comunes en pares poco líquidos como ZEC.

Los huecos se reportan pero no se rellenan: Binance no publica velas durante sus
mantenimientos y caídas.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from tradinglab.tiempo import duracion_ms

MAX_EJEMPLOS = 10


@dataclass
class Hueco:
    antes_ts: int  # última vela antes del hueco
    despues_ts: int  # primera vela después del hueco
    faltantes: int


@dataclass
class ResumenSerie:
    simbolo: str
    intervalo: str
    total: int
    primera_ts: int | None
    ultima_ts: int | None
    huecos: list[Hueco]
    invalidas: int
    ejemplos_invalidas: list[int]

    @property
    def faltantes(self) -> int:
        return sum(h.faltantes for h in self.huecos)


@dataclass
class CruceIntervalos:
    simbolo: str
    fino: str
    grueso: str
    comparadas: int = 0
    # Velas gruesas sin todas sus velas finas (por huecos): no se pueden comparar.
    incompletas: int = 0
    diferentes: int = 0
    ejemplos: list[tuple[int, str]] = field(default_factory=list)  # (ts, campos que difieren)


_CONDICION_INVALIDA = """
    minimo > maximo
    OR apertura > maximo OR apertura < minimo
    OR cierre > maximo OR cierre < minimo
    OR minimo <= 0
    OR volumen < 0 OR volumen_cotizado < 0 OR operaciones < 0
    OR compra_taker < 0 OR compra_taker > volumen
"""


def series_guardadas(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """Pares (simbolo, intervalo) que tienen al menos una vela."""
    return [
        (fila[0], fila[1])
        for fila in con.execute("SELECT DISTINCT simbolo, intervalo FROM velas ORDER BY simbolo, intervalo")
    ]


def resumir_serie(con: sqlite3.Connection, simbolo: str, intervalo: str) -> ResumenSerie:
    duracion = duracion_ms(intervalo)
    clave = (simbolo, intervalo)

    total, primera, ultima = con.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts) FROM velas WHERE simbolo = ? AND intervalo = ?",
        clave,
    ).fetchone()

    huecos = [
        Hueco(antes_ts=anterior, despues_ts=ts, faltantes=(ts - anterior) // duracion - 1)
        for anterior, ts in con.execute(
            """
            SELECT anterior, ts FROM (
                SELECT ts, LAG(ts) OVER (ORDER BY ts) AS anterior
                FROM velas WHERE simbolo = ? AND intervalo = ?
            )
            WHERE ts - anterior > ?
            ORDER BY ts
            """,
            (*clave, duracion),
        )
    ]

    invalidas = con.execute(
        f"SELECT COUNT(*) FROM velas WHERE simbolo = ? AND intervalo = ? AND ({_CONDICION_INVALIDA})",
        clave,
    ).fetchone()[0]
    ejemplos = [
        fila[0]
        for fila in con.execute(
            f"SELECT ts FROM velas WHERE simbolo = ? AND intervalo = ? AND ({_CONDICION_INVALIDA}) "
            f"ORDER BY ts LIMIT {MAX_EJEMPLOS}",
            clave,
        )
    ]

    return ResumenSerie(simbolo, intervalo, total, primera, ultima, huecos, invalidas, ejemplos)


def pares_cruzables(intervalos: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    """Pares (fino, grueso) consecutivos donde el grueso es múltiplo exacto del fino."""
    ordenados = sorted(set(intervalos), key=duracion_ms)
    return [
        (fino, grueso)
        for fino, grueso in zip(ordenados, ordenados[1:])
        if duracion_ms(grueso) % duracion_ms(fino) == 0
    ]


def _iguales(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-8)


def cruzar_intervalos(con: sqlite3.Connection, simbolo: str, fino: str, grueso: str) -> CruceIntervalos:
    """Compara cada vela gruesa con la suma de sus velas finas."""
    duracion_fina = duracion_ms(fino)
    duracion_gruesa = duracion_ms(grueso)
    if duracion_gruesa % duracion_fina != 0 or duracion_gruesa <= duracion_fina:
        raise ValueError(f"{grueso} no es múltiplo de {fino}")
    por_bloque = duracion_gruesa // duracion_fina

    filas = con.execute(
        """
        WITH bloques AS (
            -- Los precios salen solo de velas con operaciones (ver el docstring del módulo).
            SELECT (ts / :dg) * :dg AS bloque,
                   COUNT(*) AS n,
                   COALESCE(MAX(maximo) FILTER (WHERE operaciones > 0), MAX(maximo)) AS maximo,
                   COALESCE(MIN(minimo) FILTER (WHERE operaciones > 0), MIN(minimo)) AS minimo,
                   SUM(volumen) AS volumen,
                   COALESCE(MIN(ts) FILTER (WHERE operaciones > 0), MIN(ts)) AS ts_primera,
                   COALESCE(MAX(ts) FILTER (WHERE operaciones > 0), MAX(ts)) AS ts_ultima
            FROM velas
            WHERE simbolo = :s AND intervalo = :fino
            GROUP BY bloque
        )
        SELECT g.ts, g.apertura, g.maximo, g.minimo, g.cierre, g.volumen,
               b.n, fa.apertura, b.maximo, b.minimo, fc.cierre, b.volumen
        FROM velas AS g
        JOIN bloques AS b ON b.bloque = g.ts
        JOIN velas AS fa ON fa.simbolo = g.simbolo AND fa.intervalo = :fino AND fa.ts = b.ts_primera
        JOIN velas AS fc ON fc.simbolo = g.simbolo AND fc.intervalo = :fino AND fc.ts = b.ts_ultima
        WHERE g.simbolo = :s AND g.intervalo = :grueso
        ORDER BY g.ts
        """,
        {"s": simbolo, "fino": fino, "grueso": grueso, "dg": duracion_gruesa},
    ).fetchall()

    total_gruesas = con.execute(
        "SELECT COUNT(*) FROM velas WHERE simbolo = ? AND intervalo = ?", (simbolo, grueso)
    ).fetchone()[0]

    cruce = CruceIntervalos(simbolo, fino, grueso)
    # Velas gruesas sin ninguna vela fina tampoco se pueden comparar.
    cruce.incompletas = total_gruesas - len(filas)
    nombres = ("apertura", "maximo", "minimo", "cierre", "volumen")
    for ts, *resto in filas:
        gruesa, n, fina = resto[:5], resto[5], resto[6:]
        if n != por_bloque:
            cruce.incompletas += 1
            continue
        cruce.comparadas += 1
        distintos = [nombre for nombre, a, b in zip(nombres, gruesa, fina) if not _iguales(a, b)]
        if distintos:
            cruce.diferentes += 1
            if len(cruce.ejemplos) < MAX_EJEMPLOS:
                cruce.ejemplos.append((ts, ", ".join(distintos)))
    return cruce
