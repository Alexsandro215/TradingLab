"""Comandos de la línea de comandos (los registra __main__.py)."""

from __future__ import annotations

import json
import logging
import time

from tradinglab import db
from tradinglab.backtest import motor
from tradinglab.backtest.costos import Costos
from tradinglab.backtest.datos import cargar_serie
from tradinglab.backtest.estrategias import ESTRATEGIAS, obtener
from tradinglab.config import Config
from tradinglab.recolector import verificacion
from tradinglab.recolector.binance import ClienteBinance, ErrorBinance, IPBloqueada
from tradinglab.recolector.descarga import descargar_serie
from tradinglab.reporte import entero, pct, tabla, usd
from tradinglab.reporte import parametros as texto_parametros_corto
from tradinglab.tiempo import duracion_ms, fecha_a_ms, ms_a_texto
from tradinglab.validacion.barrido import correr_barrido
from tradinglab.validacion.registro import (
    fila_corrida,
    guardar_estudio,
    leer_estudio,
    listar_estudios,
    version_codigo,
)
from tradinglab.validacion.walk_forward import correr_walk_forward

log = logging.getLogger("tradinglab")


def _cuantas(n: int, singular: str, plural: str) -> str:
    """'1 vela', '2,000 velas'."""
    return f"{n:,} {singular if n == 1 else plural}"


def _normalizar_simbolos(simbolos: list[str] | None, por_defecto: tuple[str, ...]) -> list[str]:
    if not simbolos:
        return list(por_defecto)
    # Acepta "btc/usdt" o "BTCUSDT".
    return [s.upper().replace("/", "").replace("-", "") for s in simbolos]


def comando_descargar(config: Config, series: list[tuple[str, str]]) -> int:
    for _, intervalo in series:
        duracion_ms(intervalo)

    rec = config.recolector
    cliente = ClienteBinance(urls=rec.urls, pausa=rec.pausa)
    con = db.conectar(config.ruta_base)
    inicio_reloj = time.monotonic()
    fallidas: list[str] = []
    try:
        for simbolo, intervalo in series:
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


# --- Fases 2 y 3: backtest, barridos y walk-forward ---------------------------------------


def parsear_parametros(textos: list[str] | None) -> dict[str, str]:
    """['rapida=20', 'lenta=50'] -> {'rapida': '20', 'lenta': '50'}."""
    parametros: dict[str, str] = {}
    for texto in textos or []:
        clave, signo, valor = texto.partition("=")
        if not signo or not clave.strip():
            raise ValueError(f"Parámetro mal escrito: {texto!r}. Usa nombre=valor, p. ej. rapida=20")
        parametros[clave.strip()] = valor.strip()
    return parametros


def costos_de(config: Config, simbolo: str, comision: float | None, deslizamiento: float | None) -> Costos:
    base = config.costos.para(simbolo)
    return Costos(
        base.comision if comision is None else comision,
        base.deslizamiento if deslizamiento is None else deslizamiento,
    )


def _texto_costos(costos: Costos) -> str:
    return f"comisión {costos.comision:.2%} y deslizamiento {costos.deslizamiento:.2%} por lado"


def _si_no(valor: bool) -> str:
    return "SÍ" if valor else "no"


def _num(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:.2f}"


def comando_estrategias() -> int:
    for e in ESTRATEGIAS.values():
        print(f"\n{e.nombre}: {e.titulo}")
        print(f"  {e.descripcion}")
        filas = [
            (p.nombre, f"{p.por_defecto:g}", ", ".join(f"{v:g}" for v in p.rejilla), p.descripcion)
            for p in e.parametros
        ]
        print("  " + tabla(("parámetro", "por defecto", "rejilla del barrido", "qué es"), filas).replace("\n", "\n  "))
        print(f"  Combinaciones en la rejilla: {len(e.rejilla())}")
    return 0


def comando_backtest(
    config: Config,
    simbolo: str,
    intervalo: str,
    estrategia: str,
    parametros: dict[str, str],
    desde: str | None,
    hasta: str | None,
    capital: float | None,
    fraccion: float,
    comision: float | None,
    deslizamiento: float | None,
    ver_operaciones: int,
    guardar: bool,
) -> int:
    version = version_codigo()  # el código que se cargó, antes de que alguien lo edite
    e = obtener(estrategia)
    completos = e.completar(parametros)
    costos = costos_de(config, simbolo, comision, deslizamiento)
    capital = config.costos.capital_inicial if capital is None else capital
    con = db.conectar(config.ruta_base)
    try:
        serie = cargar_serie(con, simbolo, intervalo, con_factores=bool(e.factores))
        desde_ms = fecha_a_ms(desde) if desde else None
        hasta_ms = fecha_a_ms(hasta) if hasta else None
        c = motor.backtest(serie, e, completos, desde_ms, hasta_ms, costos, capital, fraccion)
        r, bh, nada = c.estrategia, c.comprar_y_mantener.metricas, c.no_operar
        m = r.metricas

        print(f"\n{simbolo} {intervalo} | {e.titulo} ({texto_parametros_corto(completos)})")
        print(f"Ventana: {ms_a_texto(int(r.ts[0]))} a {ms_a_texto(int(r.ts[-1]))} ({len(r.ts):,} velas)")
        print(f"Costos: {_texto_costos(costos)}. Capital inicial: {usd(capital)} USDT")
        if fraccion < 1:
            print(f"En cada entrada se invierte el {fraccion:.0%} del capital.")
        print()
        filas = [
            ("Rendimiento neto", pct(m.rendimiento), pct(bh.rendimiento), pct(nada.rendimiento)),
            ("Capital final (USDT)", usd(m.capital_final), usd(bh.capital_final), usd(nada.capital_final)),
            ("Drawdown máximo", pct(m.drawdown_maximo), pct(bh.drawdown_maximo), pct(nada.drawdown_maximo)),
            ("Operaciones", entero(m.operaciones), entero(bh.operaciones), entero(nada.operaciones)),
            ("Comisiones pagadas", usd(m.comisiones), usd(bh.comisiones), usd(nada.comisiones)),
            ("Costo del deslizamiento", usd(m.costo_deslizamiento), usd(bh.costo_deslizamiento), usd(0)),
            ("Operaciones ganadoras", pct(m.ganadoras, False), pct(bh.ganadoras, False), "-"),
            ("Tiempo dentro del mercado", pct(m.exposicion, False), pct(bh.exposicion, False), pct(0, False)),
            ("Rendimiento anual", pct(m.rendimiento_anual), pct(bh.rendimiento_anual), pct(0)),
            ("Calmar (anual / caída)", _num(m.calmar), _num(bh.calmar), "-"),
        ]
        print(tabla(("", "Estrategia", "Comprar y mantener", "No operar"), filas))
        print()
        print(f"¿Le gana a no operar? {_si_no(c.le_gana_a_no_operar)}.  "
              f"¿Le gana a comprar y mantener? {_si_no(c.le_gana_a_comprar_y_mantener)}.")
        print("Ojo: un solo backtest dentro de muestra no es evidencia; la evidencia sale del walk-forward.")

        if ver_operaciones and r.operaciones:
            print(f"\nÚltimas {min(ver_operaciones, len(r.operaciones))} de {len(r.operaciones):,} operaciones:")
            filas = [
                (ms_a_texto(op.entrada_ts), ms_a_texto(op.salida_ts), f"{op.precio_entrada:,.4f}",
                 f"{op.precio_salida:,.4f}", usd(op.ganancia), pct(op.rendimiento))
                for op in r.operaciones[-ver_operaciones:]
            ]
            print(tabla(("entrada", "salida", "precio entrada", "precio salida", "ganancia USDT", "rend."), filas, 2))

        if guardar:
            fila = fila_corrida(simbolo, intervalo, estrategia, completos, "personalizada", "completa",
                                int(r.ts[0]), int(r.ts[-1]) + duracion_ms(intervalo), m, bh)
            configuracion = {"simbolo": simbolo, "intervalo": intervalo, "estrategia": estrategia,
                             "parametros": completos, "desde": desde, "hasta": hasta, "capital": capital,
                             "fraccion": fraccion, "comision": costos.comision, "deslizamiento": costos.deslizamiento}
            descripcion = f"{simbolo} {intervalo} {estrategia} {texto_parametros_corto(completos)}"
            estudio_id = guardar_estudio(con, "backtest", descripcion, configuracion, [fila], {"corrida": fila},
                                         1, serie.fin_ms, version)
            print(f"\nGuardado como estudio #{estudio_id}.")
    finally:
        con.close()
    return 0


def imprimir_barrido(resumen: dict) -> None:
    total = resumen["total"]
    if not total:
        print("El barrido no produjo corridas.")
        return
    n = total["corridas"]
    print(f"\nTOTAL: {n:,} simulaciones (todas dentro de muestra).")
    for texto, clave in (("no operar", "ganan_a_no_operar"), ("comprar y mantener", "ganan_a_comprar_y_mantener"),
                         ("las dos", "ganan_a_ambas")):
        print(f"  Le ganan a {texto + ':':<20} {total[clave]:>7,} ({total[clave] / n:.1%})")

    print("\nPor estrategia:")
    filas = [
        (g["estrategia"], f"{g['corridas']:,}", pct(g["mediana"]),
         f"{g['ganan_a_no_operar'] / g['corridas']:.0%}", f"{g['ganan_a_comprar_y_mantener'] / g['corridas']:.0%}",
         f"{g['ganan_a_ambas'] / g['corridas']:.0%}")
        for g in resumen["por_estrategia"]
    ]
    print(tabla(("estrategia", "corridas", "mediana", "ganan a no operar", "a comprar y mantener", "a las dos"), filas))

    grupos: dict[tuple, list] = {}
    for g in resumen["por_ventana"]:
        grupos.setdefault((g["simbolo"], g["intervalo"]), []).append(g)
    for (simbolo, intervalo), filas_grupo in grupos.items():
        print(f"\n{simbolo} {intervalo}")
        filas = []
        for g in filas_grupo:
            mejor = g["mejor"]
            filas.append((
                g["ventana"], pct(g["bh_rendimiento"]), pct(g["mediana"]), pct(mejor["rendimiento"]),
                f"{mejor['estrategia']} {texto_parametros_corto(json.loads(mejor['parametros']))}",
                f"{g['ganan_a_ambas']}/{g['corridas']}",
            ))
        print(tabla(("ventana", "comprar y mantener", "mediana", "mejor", "mejor combinación", "ganan a las dos"),
                    filas))
    print("\nRecuerda: el 'mejor' de muchas combinaciones está inflado por suerte (sobreajuste). "
          "Lo que cuenta es el walk-forward.")


def comando_barrido(
    config: Config,
    simbolos: list[str],
    intervalos: list[str],
    estrategias: list[str],
    tipos_ventana: list[str],
    capital: float | None,
    fraccion: float,
    guardar: bool,
) -> int:
    version = version_codigo()
    for nombre in estrategias:
        obtener(nombre)
    capital = config.costos.capital_inicial if capital is None else capital
    con = db.conectar(config.ruta_base)
    inicio = time.monotonic()
    try:
        resultado = correr_barrido(con, simbolos, intervalos, estrategias, tipos_ventana, config.costos,
                                   capital, fraccion, avisar=log.info)
        log.info("Barrido listo en %.1f s", time.monotonic() - inicio)
        imprimir_barrido(resultado.resumen)
        if guardar:
            configuracion = {
                "simbolos": simbolos, "intervalos": intervalos, "estrategias": estrategias,
                "ventanas": tipos_ventana, "capital": capital, "fraccion": fraccion,
                "comision": config.costos.comision, "deslizamiento": config.costos.deslizamiento,
                "deslizamiento_por_par": config.costos.deslizamiento_por_par,
            }
            descripcion = f"{', '.join(estrategias)} en {', '.join(simbolos)} {', '.join(intervalos)}"
            estudio_id = guardar_estudio(con, "barrido", descripcion, configuracion, resultado.corridas,
                                         resultado.resumen, len(resultado.corridas), resultado.datos_hasta_ms,
                                         version)
            print(f"\nGuardado como estudio #{estudio_id} ({len(resultado.corridas):,} corridas).")
    finally:
        con.close()
    return 0


def imprimir_walk_forward(resumenes: list[dict], detalle: list[list[dict]] | None = None) -> None:
    if detalle:
        for r, pliegues in zip(resumenes, detalle):
            print(f"\n{r['simbolo']} {r['intervalo']} {r['estrategia']}: pliegue por pliegue")
            filas = [
                (p["pliegue"], ms_a_texto(p["prueba_desde_ms"])[:10], texto_parametros_corto(p["parametros"]),
                 pct(p["rendimiento_entrenamiento"]), pct(p["bh_entrenamiento"]),
                 pct(p["rendimiento_prueba"]), pct(p["bh_prueba"]), p["operaciones_prueba"])
                for p in pliegues
            ]
            print(tabla(("pliegue", "prueba desde", "elegida en entrenamiento", "rend. entren.", "C&M entren.",
                         "rend. prueba", "C&M prueba", "ops"), filas, 3))

    r0 = resumenes[0]
    anclado = ", anclado" if r0["anclado"] else ""
    print(f"\nWalk-forward: {r0['meses_entrenamiento']} meses de entrenamiento y {r0['meses_prueba']} de prueba, "
          f"criterio '{r0['criterio']}'{anclado}. Solo resultados FUERA de muestra (C&M = comprar y mantener):")
    filas = [
        (r["simbolo"], r["intervalo"], r["estrategia"], pct(r["rendimiento"]), pct(r["drawdown_maximo"]),
         f"{r['operaciones']:,}", pct(r["bh_rendimiento"]), pct(r["bh_drawdown"]),
         f"{pct(r['mensual_entrenamiento_promedio'])} -> {pct(r['mensual_prueba_promedio'])}",
         _si_no(r["le_gana_a_no_operar"]), _si_no(r["le_gana_a_comprar_y_mantener"]))
        for r in resumenes
    ]
    print(tabla(("par", "int.", "estrategia", "rendimiento", "drawdown", "ops", "C&M", "C&M dd",
                 "mensual entren. -> prueba", "gana a no operar", "gana a C&M"), filas, 3))
    if all("calmar" in r for r in resumenes):
        print("\nRiesgo fuera de muestra. Calmar = rendimiento anual / |drawdown máximo|: más alto es mejor. "
              "'Caída 1/3 menor' = drawdown al menos un tercio menor que el de C&M.")
        filas = [
            (r["simbolo"], r["intervalo"], r["estrategia"], pct(r["rendimiento_anual"]), pct(r["drawdown_maximo"]),
             _num(r["calmar"]), pct(r["bh_rendimiento_anual"]), pct(r["bh_drawdown"]), _num(r["bh_calmar"]),
             _si_no(r["drawdown_maximo"] >= r["bh_drawdown"] * 2 / 3),
             _si_no((r["calmar"] or 0) > (r["bh_calmar"] or 0)))
            for r in resumenes
        ]
        print(tabla(("par", "int.", "estrategia", "anual", "drawdown", "calmar", "C&M anual", "C&M dd",
                     "C&M calmar", "caída 1/3 menor", "mejor calmar"), filas, 3))
    n = len(resumenes)
    a_nada = sum(r["le_gana_a_no_operar"] for r in resumenes)
    a_bh = sum(r["le_gana_a_comprar_y_mantener"] for r in resumenes)
    a_ambas = sum(r["le_gana_a_no_operar"] and r["le_gana_a_comprar_y_mantener"] for r in resumenes)
    simulaciones = sum(r["simulaciones"] for r in resumenes)
    print(f"\nFuera de muestra ({ms_a_texto(r0['oos_desde_ms'])[:10]} a {ms_a_texto(r0['oos_hasta_ms'])[:10]}): "
          f"de {n} configuraciones, {a_nada} le ganan a no operar, {a_bh} a comprar y mantener "
          f"y {a_ambas} a las dos. Simulaciones corridas: {simulaciones:,}.")
    print("'mensual entren. -> prueba' compara lo que prometía la combinación elegida con lo que logró "
          "después: si cae mucho, era sobreajuste.")


def comando_walk_forward(
    config: Config,
    simbolos: list[str],
    intervalos: list[str],
    estrategias: list[str],
    meses_entrenamiento: int,
    meses_prueba: int,
    criterio: str,
    anclado: bool,
    capital: float | None,
    fraccion: float,
    detalle: bool,
    guardar: bool,
) -> int:
    version = version_codigo()
    for nombre in estrategias:
        obtener(nombre)
    capital = config.costos.capital_inicial if capital is None else capital
    con = db.conectar(config.ruta_base)
    inicio = time.monotonic()
    resumenes, pliegues, corridas = [], [], []
    datos_hasta = 0
    try:
        for simbolo in simbolos:
            for intervalo in intervalos:
                for estrategia in estrategias:
                    r = correr_walk_forward(con, simbolo, intervalo, estrategia, meses_entrenamiento, meses_prueba,
                                            criterio, config.costos.para(simbolo), capital, fraccion, anclado)
                    resumenes.append(r.resumen)
                    pliegues.append(r.pliegues)
                    corridas.extend(r.corridas)
                    datos_hasta = max(datos_hasta, r.resumen["oos_hasta_ms"])
                    log.info("%s %s %s: %d pliegues, %s simulaciones", simbolo, intervalo, estrategia,
                             r.resumen["pliegues"], f"{r.resumen['simulaciones']:,}")
        log.info("Walk-forward listo en %.1f s", time.monotonic() - inicio)
        imprimir_walk_forward(resumenes, pliegues if detalle else None)
        if guardar:
            configuracion = {
                "simbolos": simbolos, "intervalos": intervalos, "estrategias": estrategias,
                "meses_entrenamiento": meses_entrenamiento, "meses_prueba": meses_prueba, "criterio": criterio,
                "anclado": anclado, "capital": capital, "fraccion": fraccion,
                "comision": config.costos.comision, "deslizamiento": config.costos.deslizamiento,
                "deslizamiento_por_par": config.costos.deslizamiento_por_par,
            }
            descripcion = (f"{', '.join(estrategias)} en {', '.join(simbolos)} {', '.join(intervalos)} "
                           f"({meses_entrenamiento}m/{meses_prueba}m, {criterio})")
            estudio_id = guardar_estudio(con, "walk_forward", descripcion, configuracion, corridas,
                                         {"resumenes": resumenes, "pliegues": pliegues}, len(corridas), datos_hasta,
                                         version)
            print(f"\nGuardado como estudio #{estudio_id} ({len(corridas):,} corridas).")
    finally:
        con.close()
    return 0


# --- Fase 6: factores externos y estudio de eventos ------------------------------------------


def comando_factores(config: Config, simbolos: list[str]) -> int:
    """Descarga funding, métricas de futuros y miedo y codicia (incremental)."""
    from datetime import datetime, timedelta, timezone

    from tradinglab.factores.descarga import (
        ArchivosBinance,
        descargar_funding,
        descargar_metricas,
        descargar_miedo_codicia,
    )

    fac = config.factores
    con = db.conectar(config.ruta_base)
    fallos = 0
    try:
        try:
            dias = descargar_miedo_codicia(con, fac.url_miedo_codicia)
            log.info("Miedo y codicia: %s días", f"{dias:,}")
        except Exception as error:  # servicio externo: que no tumbe lo demás
            log.error("Miedo y codicia: no se pudo descargar. %s", error)
            fallos += 1

        futuros = ClienteBinance(urls=[fac.url_futuros], pausa=0.2, limite_peso=2400)
        archivos = ArchivosBinance(fac.url_archivos)
        inicio = datetime.fromtimestamp(config.recolector.inicio_ms / 1000, tz=timezone.utc).date()
        ayer = datetime.now(timezone.utc).date() - timedelta(days=1)
        for simbolo in simbolos:
            try:
                n = descargar_funding(con, futuros, simbolo, config.recolector.inicio_ms)
                log.info("%s: %s tasas de funding nuevas", simbolo, f"{n:,}")
                filas, faltan = descargar_metricas(con, archivos, simbolo, inicio, ayer, avisar=log.info)
                log.info("%s: %s registros de métricas de futuros nuevos%s", simbolo, f"{filas:,}",
                         f" ({faltan} días sin archivo)" if faltan else "")
            except ErrorBinance as error:
                log.error("%s: %s", simbolo, error)
                fallos += 1
    finally:
        con.close()
    return 1 if fallos else 0


def _x(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:.2f}x"


def imprimir_eventos(resultados: list[dict]) -> None:
    from tradinglab.factores.tabla import FACTORES

    for r in resultados:
        ent, pru = r["entrenamiento"], r["prueba"]
        corte = ms_a_texto(r["corte_ms"])[:10]
        print(f"\n{r['simbolo']} {r['intervalo']}: 'caída' = rendimiento a {r['horizonte_h']} h de "
              f"{pct(r['umbral_caida'])} o peor (el 5% peor del entrenamiento).")
        print(f"  Entrenamiento hasta {corte}: {ent['caidas_independientes']} caídas independientes. "
              f"Prueba desde {corte}: {pru['caidas_independientes']} caídas independientes "
              f"(tasa base en prueba {pct(pru['tasa_base'], False)}).")
        filas = []
        for f in r["factores"]:
            nombre = f["factor"] + (" (ref.)" if f["referencia"] else "")
            if not f["evaluado"]:
                desde = ms_a_texto(f["desde_ms"])[:10] if f["desde_ms"] else "sin datos"
                filas.append((nombre, desde, "-", "-", "-", "-", "-", "pocos datos", "-", "-"))
                continue
            quintil = f["quintil_riesgoso"]
            etiqueta = {1: "1 (más bajo)", 5: "5 (más alto)"}.get(quintil, str(quintil))
            filas.append((
                nombre, ms_a_texto(f["desde_ms"])[:10],
                f"{f['correlacion_entrenamiento']:+.3f}", f"{f['correlacion_prueba']:+.3f}", etiqueta,
                f"{pct(f['p_caida_entrenamiento'], False)} ({_x(f['lift_entrenamiento'])})",
                f"{pct(f['p_caida_prueba'], False)} ({_x(f['lift_prueba'])})",
                _si_no(f["se_sostiene"]),
                "-" if f["referencia"] else
                f"{_x(f['sobre_volatilidad_entrenamiento'])} -> {_x(f['sobre_volatilidad_prueba'])}",
                "-" if f["referencia"] else _si_no(f["agrega_sobre_volatilidad"]),
            ))
        encabezados = ("factor", "datos desde", "corr. entren.", "corr. prueba", "quintil con más caídas",
                       "P(caída) entren.", "P(caída) prueba", "¿se sostiene?", "vs. volatilidad ent. -> prueba",
                       "¿agrega?")
        print("  " + tabla(encabezados, filas, {0, 1}).replace("\n", "\n  "))
    print("\n'Se sostiene' = el quintil con más caídas en entrenamiento también tiene al menos 1.25 veces "
          "la tasa base en la prueba. La correlación es contra el rendimiento de las horas siguientes.")
    print("'vs. volatilidad' = caídas en el quintil riesgoso del factor entre las que predeciría la volatilidad "
          "sola. Cerca de 1.00x: el factor solo repite la volatilidad. '¿Agrega?' = se sostiene y queda en "
          "1.20x o más en entrenamiento y en prueba.")
    print("Qué mide cada factor:")
    for nombre, descripcion in FACTORES.items():
        print(f"  {nombre}: {descripcion}")


def comando_eventos(config: Config, simbolos: list[str], intervalo: str, horizonte: int, corte: str,
                    guardar: bool) -> int:
    from tradinglab.factores.eventos import estudiar_serie

    version = version_codigo()
    corte_ms = fecha_a_ms(corte)
    con = db.conectar(config.ruta_base)
    try:
        resultados = [estudiar_serie(con, s, intervalo, horizonte, corte_ms) for s in simbolos]
        imprimir_eventos(resultados)
        if guardar:
            configuracion = {"simbolos": simbolos, "intervalo": intervalo, "horizonte_h": horizonte, "corte": corte}
            evaluados = sum(f["evaluado"] for r in resultados for f in r["factores"])
            descripcion = (f"factores contra caídas a {horizonte} h en {', '.join(simbolos)} {intervalo} "
                           f"(corte {corte})")
            estudio_id = guardar_estudio(con, "eventos", descripcion, configuracion, [], {"resultados": resultados},
                                         evaluados, max(r["fin_ms"] for r in resultados), version)
            print(f"\nGuardado como estudio #{estudio_id} ({evaluados} factores evaluados).")
    finally:
        con.close()
    return 0


# --- Fase 4: panel web ----------------------------------------------------------------------


def comando_panel(config: Config, puerto: int | None, abrir: bool) -> int:
    import threading
    import webbrowser

    import uvicorn

    from tradinglab.panel.app import crear_app

    if not config.ruta_base.exists():
        print(f"No existe la base {config.ruta_base}. Corre primero: python -m tradinglab descargar")
        return 1
    db.conectar(config.ruta_base).close()  # migra el esquema si hace falta (el panel solo lee)
    puerto = puerto or config.puerto_panel
    url = f"http://127.0.0.1:{puerto}"
    print(f"Panel en {url}  (Ctrl+C para detenerlo)")
    if abrir:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(crear_app(config), host="127.0.0.1", port=puerto, log_level="warning")
    return 0


# --- Fase 5: operación en papel -----------------------------------------------------------


def _imprimir_sesiones(con) -> None:
    from tradinglab.papel.operador import resumen_sesion

    nombres = [f[0] for f in con.execute("SELECT nombre FROM papel_sesiones ORDER BY creada_ms")]
    if not nombres:
        print("No hay sesiones de papel.")
        return
    filas = []
    for nombre in nombres:
        s = resumen_sesion(con, nombre)
        filas.append((s["nombre"], f"{s['simbolo']} {s['intervalo']}",
                      f"{s['estrategia']} {texto_parametros_corto(s['parametros'])}", usd(s["capital"]),
                      pct(s["rendimiento"]), pct(s["bh_rendimiento"]), s["operaciones"],
                      "comprado" if s["cantidad"] > 0 else "fuera", ms_a_texto(s["actualizada_ms"])))
    print(tabla(("sesión", "serie", "estrategia", "capital", "rendimiento", "C&M desde el inicio", "ops",
                 "posición", "actualizada"), filas, 3))


def comando_papel(config: Config, args) -> int:
    import asyncio

    from tradinglab.papel.en_vivo import operar
    from tradinglab.papel.operador import ConfigSesion, Operador, borrar_sesion, leer_sesion

    con = db.conectar(config.ruta_base)
    try:
        if args.listar:
            _imprimir_sesiones(con)
            return 0

        simbolo = _normalizar_simbolos([args.simbolo], ())[0] if args.simbolo else None
        dados = (simbolo, args.intervalo, args.estrategia)
        nombre = args.nombre or ("-".join(dados) if all(dados) else None)
        if not nombre:
            raise ValueError("Indica --nombre de una sesión existente, o --simbolo, --intervalo y --estrategia")
        existente = leer_sesion(con, nombre)
        if existente and args.reiniciar:
            borrar_sesion(con, nombre)
            existente = None

        if existente and not any(dados) and not args.param:
            sesion = existente  # retomar tal cual
        else:
            if not all(dados):
                raise ValueError("Para una sesión nueva hacen falta --simbolo, --intervalo y --estrategia")
            duracion_ms(args.intervalo)
            e = obtener(args.estrategia)
            sesion = ConfigSesion(
                nombre=nombre, simbolo=simbolo, intervalo=args.intervalo, estrategia=args.estrategia,
                parametros=e.completar(parsear_parametros(args.param)),
                capital_inicial=config.costos.capital_inicial if args.capital is None else args.capital,
                fraccion=args.fraccion, costos=config.costos.para(simbolo),
            )
            if existente and not existente.misma_configuracion(sesion):
                raise ValueError(f"La sesión {nombre!r} ya existe con otra configuración. "
                                 "Usa --reiniciar para empezarla de cero, u otro --nombre.")

        operador = Operador(con, sesion)
        print(f"Operación en PAPEL (sin dinero real): {sesion.nombre} | {sesion.simbolo} {sesion.intervalo} | "
              f"{sesion.estrategia} {texto_parametros_corto(operador.parametros)} | {_texto_costos(sesion.costos)}")
        print("Ctrl+C para detener; la sesión se guarda y se retoma con el mismo --nombre.", flush=True)
        cliente = ClienteBinance(urls=config.recolector.urls, pausa=config.recolector.pausa)
        try:
            asyncio.run(operar(con, cliente, operador, minutos=args.minutos))
        except KeyboardInterrupt:
            log.info("Detenido por el usuario.")
        print()
        _imprimir_sesiones(con)
    finally:
        con.close()
    return 0


def comando_estudios(config: Config, estudio_id: int | None) -> int:
    con = db.conectar(config.ruta_base)
    try:
        if estudio_id is None:
            estudios = listar_estudios(con)
            if not estudios:
                print("Todavía no hay estudios guardados.")
                return 0
            filas = [(f"#{e['id']}", ms_a_texto(e["creado_ms"]), e["tipo"], f"{e['combinaciones']:,}",
                      e["commit_git"] or "-", e["descripcion"]) for e in estudios]
            print(tabla(("id", "fecha", "tipo", "simulaciones", "commit", "descripción"), filas, {0, 1, 2, 5}))
            return 0
        e = leer_estudio(con, estudio_id)
        if e is None:
            print(f"No existe el estudio #{estudio_id}.")
            return 1
        print(f"Estudio #{e['id']} ({e['tipo']}), {ms_a_texto(e['creado_ms'])}, commit {e['commit_git'] or '-'}")
        print(e["descripcion"])
        print(f"Datos hasta {ms_a_texto(e['datos_hasta_ms'])}. Simulaciones: {e['combinaciones']:,}")
        if e["tipo"] == "barrido":
            imprimir_barrido(e["resumen"])
        elif e["tipo"] == "walk_forward":
            imprimir_walk_forward(e["resumen"]["resumenes"], e["resumen"]["pliegues"])
        elif e["tipo"] == "eventos":
            imprimir_eventos(e["resumen"]["resultados"])
        else:
            print(json.dumps(e["resumen"], indent=2, ensure_ascii=False))
    finally:
        con.close()
    return 0
