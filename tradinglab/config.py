"""Configuración del proyecto, leída de config.toml en la raíz."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from tradinglab.tiempo import duracion_ms, fecha_a_ms

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.toml"


@dataclass(frozen=True)
class ConfigRecolector:
    simbolos: tuple[str, ...]
    intervalos: tuple[str, ...]
    inicio_ms: int
    urls: tuple[str, ...]
    pausa: float


@dataclass(frozen=True)
class Config:
    ruta_base: Path
    recolector: ConfigRecolector


def cargar_config(ruta: Path = RUTA_CONFIG) -> Config:
    """Lee config.toml. Las rutas relativas se resuelven desde la carpeta del archivo."""
    with open(ruta, "rb") as archivo:
        datos = tomllib.load(archivo)

    ruta_base = Path(datos["datos"]["ruta_base"])
    if not ruta_base.is_absolute():
        ruta_base = ruta.parent / ruta_base

    rec = datos["recolector"]
    intervalos = tuple(rec["intervalos"])
    for intervalo in intervalos:
        duracion_ms(intervalo)  # falla temprano si hay un intervalo no soportado

    return Config(
        ruta_base=ruta_base,
        recolector=ConfigRecolector(
            simbolos=tuple(s.upper() for s in rec["simbolos"]),
            intervalos=intervalos,
            inicio_ms=fecha_a_ms(rec["inicio"]),
            urls=tuple(rec["urls"]),
            pausa=float(rec.get("pausa_entre_peticiones", 0.1)),
        ),
    )
