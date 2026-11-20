"""Configuración del proyecto, leída de config.toml en la raíz."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tradinglab.backtest.costos import Costos
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
    # Pares reservados para validar hipótesis (no se usan para explorar).
    simbolos_validacion: tuple[str, ...] = ()
    intervalos_validacion: tuple[str, ...] = ()

    def series(self) -> list[tuple[str, str]]:
        """Todas las series que mantiene el recolector: las de estudio y las de validación."""
        normales = [(s, i) for s in self.simbolos for i in self.intervalos]
        reservadas = [(s, i) for s in self.simbolos_validacion for i in self.intervalos_validacion]
        return normales + [x for x in reservadas if x not in normales]


@dataclass(frozen=True)
class ConfigFactores:
    url_futuros: str = "https://fapi.binance.com"
    url_archivos: str = "https://data.binance.vision"
    url_miedo_codicia: str = "https://api.alternative.me/fng/?limit=0&format=json"


@dataclass(frozen=True)
class ConfigCostos:
    comision: float = 0.001
    deslizamiento: float = 0.0005
    capital_inicial: float = 1000.0
    deslizamiento_por_par: dict[str, float] = field(default_factory=dict)

    def para(self, simbolo: str) -> Costos:
        """Costos de un par: el deslizamiento puede ser distinto por par."""
        return Costos(self.comision, self.deslizamiento_por_par.get(simbolo, self.deslizamiento))


@dataclass(frozen=True)
class Config:
    ruta_base: Path
    recolector: ConfigRecolector
    costos: ConfigCostos = ConfigCostos()
    puerto_panel: int = 8000
    factores: ConfigFactores = ConfigFactores()


def cargar_config(ruta: Path = RUTA_CONFIG) -> Config:
    """Lee config.toml. Las rutas relativas se resuelven desde la carpeta del archivo."""
    with open(ruta, "rb") as archivo:
        datos = tomllib.load(archivo)

    ruta_base = Path(datos["datos"]["ruta_base"])
    if not ruta_base.is_absolute():
        ruta_base = ruta.parent / ruta_base

    rec = datos["recolector"]
    intervalos = tuple(rec["intervalos"])
    intervalos_validacion = tuple(rec.get("intervalos_validacion", intervalos))
    for intervalo in intervalos + intervalos_validacion:
        duracion_ms(intervalo)  # falla temprano si hay un intervalo no soportado

    cos = datos.get("costos", {})
    por_par = {k.upper(): float(v) for k, v in cos.get("deslizamiento_por_par", {}).items()}
    costos = ConfigCostos(
        comision=float(cos.get("comision", 0.001)),
        deslizamiento=float(cos.get("deslizamiento", 0.0005)),
        capital_inicial=float(cos.get("capital_inicial", 1000.0)),
        deslizamiento_por_par=por_par,
    )
    costos.para("")  # valida los rangos

    return Config(
        ruta_base=ruta_base,
        recolector=ConfigRecolector(
            simbolos=tuple(s.upper() for s in rec["simbolos"]),
            intervalos=intervalos,
            inicio_ms=fecha_a_ms(rec["inicio"]),
            urls=tuple(rec["urls"]),
            pausa=float(rec.get("pausa_entre_peticiones", 0.1)),
            simbolos_validacion=tuple(s.upper() for s in rec.get("simbolos_validacion", ())),
            intervalos_validacion=intervalos_validacion,
        ),
        costos=costos,
        puerto_panel=int(datos.get("panel", {}).get("puerto", 8000)),
        factores=ConfigFactores(**datos.get("factores", {})),
    )
