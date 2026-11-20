"""Línea de comandos de TradingLab: python -m tradinglab <comando> [opciones].

Fase 1  descargar, verificar
Fase 2  estrategias, backtest
Fase 3  barrido, walk-forward, estudios
Fase 4  panel
Fase 5  papel
Fase 6  factores, eventos

Usa `python -m tradinglab <comando> --help` para ver las opciones de cada uno.
"""

from __future__ import annotations

import argparse
import logging
import sys

from tradinglab import comandos
from tradinglab.backtest.estrategias import ESTRATEGIAS
from tradinglab.config import cargar_config
from tradinglab.validacion.ventanas import TIPOS_VENTANA
from tradinglab.validacion.walk_forward import CRITERIOS


def _simbolos(valores: list[str] | None, por_defecto: tuple[str, ...]) -> list[str]:
    return comandos._normalizar_simbolos(valores, por_defecto)


def _estrategias(valores: list[str] | None) -> list[str]:
    if not valores or "todas" in valores:
        return list(ESTRATEGIAS)
    return valores


def _opciones_de_simulacion(p: argparse.ArgumentParser) -> None:
    p.add_argument("--capital", type=float, help="capital inicial en USDT (por defecto el de config.toml)")
    p.add_argument("--fraccion", type=float, default=1.0,
                   help="fracción del capital que se invierte en cada entrada (por defecto 1 = todo)")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tradinglab",
        description="TradingLab: laboratorio de investigación de trading (sin dinero real).",
    )
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    # Fase 1
    p = sub.add_parser("descargar", help="descarga o actualiza las velas de Binance (incremental)")
    p.add_argument("--simbolo", action="append", help="par, p. ej. BTCUSDT (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--intervalo", action="append", help="intervalo, p. ej. 5m (se puede repetir; por defecto los de config.toml)")

    p = sub.add_parser("verificar", help="resumen y control de calidad de las velas guardadas")
    p.add_argument("--simbolo", action="append", help="limitar a este par (se puede repetir)")
    p.add_argument("--intervalo", action="append", help="limitar a este intervalo (se puede repetir)")
    p.add_argument("--max-huecos", type=int, default=5, help="cuántos huecos listar por serie (por defecto 5)")

    # Fase 2
    sub.add_parser("estrategias", help="lista las estrategias, sus parámetros y sus rejillas")

    p = sub.add_parser("backtest", help="corre una estrategia y la compara con no operar y con comprar y mantener")
    p.add_argument("--simbolo", required=True, help="p. ej. BTCUSDT")
    p.add_argument("--intervalo", default="1h", help="por defecto 1h")
    p.add_argument("--estrategia", required=True, choices=list(ESTRATEGIAS))
    p.add_argument("--param", action="append", metavar="NOMBRE=VALOR", help="parámetro de la estrategia (se puede repetir)")
    p.add_argument("--desde", help="fecha inicial en UTC, p. ej. 2022-01-01 (por defecto, el inicio de los datos)")
    p.add_argument("--hasta", help="fecha final en UTC, sin incluirla (por defecto, el final de los datos)")
    _opciones_de_simulacion(p)
    p.add_argument("--comision", type=float, help="comisión por lado como fracción (0.001 = 0.1%%)")
    p.add_argument("--deslizamiento", type=float, help="deslizamiento por lado como fracción (0.0005 = 0.05%%)")
    p.add_argument("--operaciones", type=int, default=0, metavar="N", help="mostrar las últimas N operaciones")
    p.add_argument("--guardar", action="store_true", help="guardar el resultado como estudio")

    # Fase 3
    p = sub.add_parser("barrido", help="corridas masivas: todas las combinaciones en muchas ventanas")
    p.add_argument("--estrategia", action="append", help="estrategia (se puede repetir; por defecto todas)")
    p.add_argument("--simbolo", action="append", help="par (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--intervalo", action="append", help="intervalo (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--ventanas", default="completa,anual,hasta_hoy",
                   help=f"tipos de ventana separados por comas: {', '.join(TIPOS_VENTANA)} (por defecto completa,anual,hasta_hoy)")
    _opciones_de_simulacion(p)
    p.add_argument("--no-guardar", action="store_true", help="no guardar el estudio en la base")

    p = sub.add_parser("walk-forward", help="validación fuera de muestra")
    p.add_argument("--estrategia", action="append", help="estrategia (se puede repetir; por defecto todas)")
    p.add_argument("--simbolo", action="append", help="par (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--intervalo", action="append", help="intervalo (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--entrenamiento", type=int, default=12, help="meses de entrenamiento (por defecto 12)")
    p.add_argument("--prueba", type=int, default=3, help="meses de prueba (por defecto 3)")
    p.add_argument("--criterio", choices=CRITERIOS, default="rendimiento",
                   help="cómo se elige la mejor combinación en entrenamiento (por defecto rendimiento)")
    p.add_argument("--anclado", action="store_true", help="el entrenamiento siempre empieza al inicio de los datos")
    _opciones_de_simulacion(p)
    p.add_argument("--detalle", action="store_true", help="mostrar cada pliegue")
    p.add_argument("--no-guardar", action="store_true", help="no guardar el estudio en la base")

    p = sub.add_parser("estudios", help="lista los estudios guardados o muestra uno")
    p.add_argument("id", nargs="?", type=int, help="número del estudio a mostrar")

    # Fase 6
    p = sub.add_parser("factores", help="descarga funding, métricas de futuros y miedo y codicia (incremental)")
    p.add_argument("--simbolo", action="append",
                   help="par (se puede repetir; por defecto los de estudio y los de validación)")

    p = sub.add_parser("eventos", help="estudio de eventos: ¿algún factor avisa antes de las caídas fuertes?")
    p.add_argument("--simbolo", action="append", help="par (se puede repetir; por defecto los de config.toml)")
    p.add_argument("--intervalo", default="1h", help="por defecto 1h")
    p.add_argument("--horizonte", type=int, default=24,
                   help="horas hacia adelante para medir la caída (por defecto 24)")
    p.add_argument("--corte", default="2024-01-01",
                   help="fecha que separa entrenamiento y prueba (por defecto 2024-01-01)")
    p.add_argument("--no-guardar", action="store_true", help="no guardar el estudio en la base")

    # Fase 4
    p = sub.add_parser("panel", help="abre el panel web")
    p.add_argument("--puerto", type=int, help="puerto (por defecto el de config.toml)")
    p.add_argument("--abrir", action="store_true", help="abrir el navegador")

    # Fase 5
    p = sub.add_parser("papel", help="operación en papel con datos en vivo (sin dinero real)")
    p.add_argument("--nombre", help="nombre de la sesión (por defecto par-intervalo-estrategia)")
    p.add_argument("--simbolo", help="p. ej. BTCUSDT (no hace falta si la sesión ya existe)")
    p.add_argument("--intervalo", help="p. ej. 5m")
    p.add_argument("--estrategia", choices=list(ESTRATEGIAS))
    p.add_argument("--param", action="append", metavar="NOMBRE=VALOR", help="parámetro de la estrategia")
    _opciones_de_simulacion(p)
    p.add_argument("--reiniciar", action="store_true", help="borrar la sesión con ese nombre y empezar de cero")
    p.add_argument("--minutos", type=float, help="detenerse después de estos minutos (por defecto, nunca)")
    p.add_argument("--listar", action="store_true", help="solo listar las sesiones guardadas")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    config = cargar_config()
    rec = config.recolector

    try:
        if args.comando == "descargar":
            if args.simbolo or args.intervalo:
                simbolos = _simbolos(args.simbolo, rec.simbolos + rec.simbolos_validacion)
                series = [(s, i) for s in simbolos for i in (args.intervalo or list(rec.intervalos))]
            else:
                series = rec.series()
            return comandos.comando_descargar(config, series)
        if args.comando == "verificar":
            return comandos.comando_verificar(
                config, _simbolos(args.simbolo, ()) or None, args.intervalo, args.max_huecos
            )
        if args.comando == "estrategias":
            return comandos.comando_estrategias()
        if args.comando == "backtest":
            return comandos.comando_backtest(
                config, _simbolos([args.simbolo], ())[0], args.intervalo, args.estrategia,
                comandos.parsear_parametros(args.param), args.desde, args.hasta, args.capital, args.fraccion,
                args.comision, args.deslizamiento, args.operaciones, args.guardar,
            )
        if args.comando == "barrido":
            return comandos.comando_barrido(
                config, _simbolos(args.simbolo, rec.simbolos), args.intervalo or list(rec.intervalos),
                _estrategias(args.estrategia), [v.strip() for v in args.ventanas.split(",") if v.strip()],
                args.capital, args.fraccion, not args.no_guardar,
            )
        if args.comando == "walk-forward":
            return comandos.comando_walk_forward(
                config, _simbolos(args.simbolo, rec.simbolos), args.intervalo or list(rec.intervalos),
                _estrategias(args.estrategia), args.entrenamiento, args.prueba, args.criterio, args.anclado,
                args.capital, args.fraccion, args.detalle, not args.no_guardar,
            )
        if args.comando == "estudios":
            return comandos.comando_estudios(config, args.id)
        if args.comando == "factores":
            return comandos.comando_factores(config, _simbolos(args.simbolo, rec.simbolos + rec.simbolos_validacion))
        if args.comando == "eventos":
            return comandos.comando_eventos(config, _simbolos(args.simbolo, rec.simbolos), args.intervalo,
                                            args.horizonte, args.corte, not args.no_guardar)
        if args.comando == "panel":
            return comandos.comando_panel(config, args.puerto, args.abrir)
        if args.comando == "papel":
            return comandos.comando_papel(config, args)
    except ValueError as error:
        # Errores de uso (parámetros, fechas, series sin datos): mensaje claro, sin traza.
        print(f"Error: {error}", file=sys.stderr)
        return 2
    parser.error(f"comando desconocido: {args.comando}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
