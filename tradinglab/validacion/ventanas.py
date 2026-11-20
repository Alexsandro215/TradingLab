"""Ventanas de tiempo para barridos y pliegues de walk-forward. Todo en UTC."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone

DIA_MS = 86_400_000
# Una ventana más corta que esto no se evalúa: no dice nada.
MINIMO_MS = 7 * DIA_MS

TIPOS_VENTANA = ("completa", "anual", "semestral", "hasta_hoy")


@dataclass(frozen=True)
class Ventana:
    nombre: str
    desde_ms: int
    hasta_ms: int  # exclusivo

    @property
    def dias(self) -> float:
        return (self.hasta_ms - self.desde_ms) / DIA_MS


def _fecha(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _ms(fecha: datetime) -> int:
    return int(fecha.timestamp() * 1000)


def _inicio_de(anio: int, mes: int = 1) -> int:
    return _ms(datetime(anio, mes, 1, tzinfo=timezone.utc))


def sumar_meses(fecha: datetime, meses: int) -> datetime:
    total = fecha.month - 1 + meses
    anio, mes = fecha.year + total // 12, total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)


def ventanas_estandar(tipos: list[str] | tuple[str, ...], primera_ms: int, fin_ms: int) -> list[Ventana]:
    """Ventanas de calendario dentro de [primera_ms, fin_ms).

    - completa: todo el historial.
    - anual: cada año calendario (el primero y el último pueden ser parciales).
    - semestral: cada semestre (enero-junio, julio-diciembre).
    - hasta_hoy: desde el 1 de enero de cada año hasta el final de los datos.
    """
    desde_anio, hasta_anio = _fecha(primera_ms).year, _fecha(fin_ms - 1).year
    ventanas: list[Ventana] = []

    def agregar(nombre: str, desde: int, hasta: int) -> None:
        desde, hasta = max(desde, primera_ms), min(hasta, fin_ms)
        if hasta - desde >= MINIMO_MS:
            ventanas.append(Ventana(nombre, desde, hasta))

    for tipo in tipos:
        if tipo == "completa":
            agregar("completa", primera_ms, fin_ms)
        elif tipo == "anual":
            for anio in range(desde_anio, hasta_anio + 1):
                desde, hasta = _inicio_de(anio), _inicio_de(anio + 1)
                parcial = desde < primera_ms or hasta > fin_ms
                agregar(f"{anio}{' (parcial)' if parcial else ''}", desde, hasta)
        elif tipo == "semestral":
            for anio in range(desde_anio, hasta_anio + 1):
                for semestre, (mes_desde, desde_sig) in enumerate(((1, (anio, 7)), (7, (anio + 1, 1))), 1):
                    desde, hasta = _inicio_de(anio, mes_desde), _inicio_de(*desde_sig)
                    parcial = desde < primera_ms or hasta > fin_ms
                    agregar(f"{anio}-S{semestre}{' (parcial)' if parcial else ''}", desde, hasta)
        elif tipo == "hasta_hoy":
            for anio in range(desde_anio + 1, hasta_anio + 1):
                agregar(f"{anio} a hoy", _inicio_de(anio), fin_ms)
        else:
            raise ValueError(f"Tipo de ventana desconocido: {tipo!r}. Hay: {', '.join(TIPOS_VENTANA)}")
    return ventanas


def pliegues_walk_forward(
    primera_ms: int,
    fin_ms: int,
    meses_entrenamiento: int,
    meses_prueba: int,
    anclado: bool = False,
) -> list[tuple[Ventana, Ventana]]:
    """Pares (entrenamiento, prueba) consecutivos.

    El entrenamiento dura `meses_entrenamiento` y la prueba, los `meses_prueba` siguientes.
    Cada pliegue avanza `meses_prueba`, así que las pruebas no se enciman y juntas cubren todo
    el periodo fuera de muestra. Con `anclado`, el entrenamiento siempre empieza al principio
    del historial (crece en cada pliegue).
    """
    if meses_entrenamiento < 1 or meses_prueba < 1:
        raise ValueError("Los meses de entrenamiento y de prueba deben ser al menos 1")
    inicio = _fecha(primera_ms)
    pliegues: list[tuple[Ventana, Ventana]] = []
    n = 0
    while True:
        desde_ent = primera_ms if anclado else _ms(sumar_meses(inicio, n * meses_prueba))
        hasta_ent = _ms(sumar_meses(inicio, meses_entrenamiento + n * meses_prueba))
        hasta_pru = min(_ms(sumar_meses(inicio, meses_entrenamiento + (n + 1) * meses_prueba)), fin_ms)
        if hasta_pru - hasta_ent < MINIMO_MS:
            break
        nombre = f"pliegue {n + 1}"
        pliegues.append((Ventana(nombre, desde_ent, hasta_ent), Ventana(nombre, hasta_ent, hasta_pru)))
        n += 1
    return pliegues
