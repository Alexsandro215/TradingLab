"""Línea de comandos de TradingLab.

    python -m tradinglab descargar [--simbolo BTCUSDT] [--intervalo 5m]
    python -m tradinglab verificar [--simbolo BTCUSDT] [--intervalo 5m] [--max-huecos 5]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from tradinglab import db
from tradinglab.config import Config, cargar_config
from tradinglab.recolector import verificacion
from tradinglab.recolector.binance import ClienteBinance, ErrorBinance, IPBloqueada
from tradinglab.recolector.descarga import descargar_serie
from tradinglab.tiempo import duracion_ms, ms_a_texto

log = logging.getLogger("tradinglab")


def _cuantas(n: int, singular: str, plural: str) -> str:
    """'1 vela', '2,000 velas'."""
    return f"{n:,} {singular if n == 1 else plural}"


def _normalizar_simbolos(simbolos: list[str] | None, por_defecto: tuple[str, ...]) -> list[str]:
    if not simbolos:
        return list(por_defecto)
    # Acepta "btc/usdt" o "BTCUSDT".
    return [s.upper().replace("/", "").replace("-", "") for s in simbolos]


def comando_descargar(config: Config, simbolos: list[str], intervalos: list[str]) -> int:
    for intervalo in intervalos:
        duracion_ms(intervalo)

    rec = config.recolector
    cliente = ClienteBinance(urls=rec.urls, pausa=rec.pausa)
    con = db.conectar(config.ruta_base)
    inicio_reloj = time.monotonic()
    fallidas: list[str] = []
    try:
        for simbolo in simbolos:
            for intervalo in intervalos:
                log.info("%s %s: descargando...", simbolo, intervalo)
                try:
                    r = descargar_serie(con, cliente, simbolo, intervalo, rec.inicio_ms)
                except IPBloqueada as error:
                    log.error("%s", error)
                    return 2
                except ErrorBinance as error:
                    log.error("%s %s: no se pudo descargar. %s", simbolo, intervalo, error)
                    fallidas.append(f"{simbolo} {intervalo}")
                    continue
                ultima = ms_a_texto(r.ultima_ts) if r.ultima_ts is not None else "sin velas"
                log.info(
                    "%s %s: %s nuevas en %s. Última vela: %s",
                    simbolo,
                    intervalo,
                    _cuantas(r.insertadas, "vela", "velas"),
                    _cuantas(r.lotes, "petición", "peticiones"),
                    ultima,
                )
    except KeyboardInterrupt:
        log.warning("Interrumpido. Lo guardado se conserva; la próxima corrida reanuda desde ahí.")
        return 130
    finally:
        con.close()

    minutos = (time.monotonic() - inicio_reloj) / 60
    log.info(
        "Listo en %.1f min, %s a Binance. Base: %s",
        minutos,
        _cuantas(cliente.peticiones, "petición", "peticiones"),
        config.ruta_base,
    )
    if fallidas:
        log.error("Series que fallaron: %s", ", ".join(fallidas))
        return 1
    return 0


def comando_verificar(
    config: Config, simbolos: list[str] | None, intervalos: list[str] | None, max_huecos: int
) -> int:
    if not config.ruta_base.exists():
        print(f"No existe la base {config.ruta_base}. Corre primero: python -m tradinglab descargar")
        return 1

    con = db.conectar(config.ruta_base)
    problemas = 0
    try:
        series = [
            (s, i)
            for s, i in verificacion.series_guardadas(con)
            if (not simbolos or s in simbolos) and (not intervalos or i in intervalos)
        ]
        if not series:
            print("No hay velas guardadas para esa selección.")
            return 1

        for simbolo, intervalo in series:
            r = verificacion.resumir_serie(con, simbolo, intervalo)
            print(f"\n{simbolo} {intervalo}")
            print(f"  velas: {r.total:,}   desde {ms_a_texto(r.primera_ts)}   hasta {ms_a_texto(r.ultima_ts)}")
            if r.huecos:
                print(f"  huecos: {len(r.huecos)} (faltan {r.faltantes:,} velas en total). Los más grandes:")
                duracion = duracion_ms(intervalo)
                for h in sorted(r.huecos, key=lambda h: h.faltantes, reverse=True)[:max_huecos]:
                    print(
                        f"    {ms_a_texto(h.antes_ts + duracion)} a {ms_a_texto(h.despues_ts - duracion)}"
                        f"  ({_cuantas(h.faltantes, 'vela', 'velas')})"
                    )
            else:
                print("  huecos: ninguno")
            if r.invalidas:
                problemas += 1
                ejemplos = ", ".join(ms_a_texto(ts) for ts in r.ejemplos_invalidas)
                print(f"  velas INVÁLIDAS: {r.invalidas:,}. Ejemplos: {ejemplos}")
            else:
                print("  velas inválidas: 0")

        guardadas = {i for _, i in series}
        for simbolo in sorted({s for s, _ in series}):
            for fino, grueso in verificacion.pares_cruzables(sorted(guardadas)):
                c = verificacion.cruzar_intervalos(con, simbolo, fino, grueso)
                print(
                    f"\n{simbolo} {fino} contra {grueso}: {c.comparadas:,} velas comparadas, "
                    f"{c.diferentes:,} con diferencias, {c.incompletas:,} incompletas (no se comparan)"
                )
                if c.diferentes:
                    problemas += 1
                    for ts, campos in c.ejemplos:
                        print(f"    {ms_a_texto(ts)}: difiere {campos}")
    finally:
        con.close()

    print()
    print("Verificación sin problemas." if not problemas else f"Verificación con {problemas} problema(s).")
    return 1 if problemas else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tradinglab",
        description="TradingLab: laboratorio de investigación de trading (sin dinero real).",
    )
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    p_descargar = sub.add_parser("descargar", help="descarga o actualiza las velas de Binance (incremental)")
    p_descargar.add_argument(
        "--simbolo", action="append", help="par, p. ej. BTCUSDT (se puede repetir; por defecto los de config.toml)"
    )
    p_descargar.add_argument(
        "--intervalo", action="append", help="intervalo, p. ej. 5m (se puede repetir; por defecto los de config.toml)"
    )

    p_verificar = sub.add_parser("verificar", help="resumen y control de calidad de las velas guardadas")
    p_verificar.add_argument("--simbolo", action="append", help="limitar a este par (se puede repetir)")
    p_verificar.add_argument("--intervalo", action="append", help="limitar a este intervalo (se puede repetir)")
    p_verificar.add_argument("--max-huecos", type=int, default=5, help="cuántos huecos listar por serie (por defecto 5)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    config = cargar_config()

    if args.comando == "descargar":
        simbolos = _normalizar_simbolos(args.simbolo, config.recolector.simbolos)
        intervalos = args.intervalo or list(config.recolector.intervalos)
        return comando_descargar(config, simbolos, intervalos)
    if args.comando == "verificar":
        simbolos = _normalizar_simbolos(args.simbolo, ()) or None
        return comando_verificar(config, simbolos, args.intervalo, args.max_huecos)
    parser.error(f"comando desconocido: {args.comando}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
