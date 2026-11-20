"""Panel web: velas con las operaciones marcadas, curva de capital y drawdown.

Solo lee la base (conexiones de solo lectura), así que puede correr al mismo tiempo que el
recolector o la operación en papel. Escucha solo en esta computadora (127.0.0.1).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from tradinglab import db
from tradinglab.backtest import motor
from tradinglab.backtest.costos import Costos
from tradinglab.backtest.datos import Serie, cargar_serie
from tradinglab.backtest.estrategias import ESTRATEGIAS, obtener
from tradinglab.config import Config
from tradinglab.papel.operador import resumen_sesion
from tradinglab.tiempo import duracion_ms, fecha_a_ms
from tradinglab.validacion import registro

ESTATICOS = Path(__file__).parent / "static"
# Más velas que esto vuelve lento al navegador (5m de varios años son ~700 mil).
MAX_VELAS = 150_000


def _segundos(ts_ms: np.ndarray) -> list[int]:
    """Lightweight Charts usa segundos desde epoch (UTC)."""
    return (ts_ms // 1000).astype(np.int64).tolist()


def _puntos(ts_ms: np.ndarray, valores: np.ndarray, decimales: int = 6) -> list[dict[str, float]]:
    return [{"time": t, "value": v} for t, v in zip(_segundos(ts_ms), np.round(valores, decimales).tolist())]


def _velas(serie: Serie, inicio: int, fin: int) -> list[dict[str, float]]:
    v = serie.velas.iloc[inicio:fin]
    return [
        {"time": t, "open": o, "high": h, "low": l, "close": c}
        for t, o, h, l, c in zip(
            _segundos(v["ts"].to_numpy()),
            v["apertura"].tolist(), v["maximo"].tolist(), v["minimo"].tolist(), v["cierre"].tolist(),
        )
    ]


def _fecha(texto: str | None) -> int | None:
    if not texto:
        return None
    try:
        return fecha_a_ms(texto)
    except ValueError:
        raise HTTPException(400, f"Fecha inválida: {texto!r}. Usa AAAA-MM-DD") from None


def crear_app(config: Config) -> FastAPI:
    app = FastAPI(title="TradingLab", docs_url="/api/docs", redoc_url=None)
    cache: dict[tuple[str, str, bool], tuple[int, Serie]] = {}
    candado = threading.Lock()

    def conexion() -> sqlite3.Connection:
        if not config.ruta_base.exists():
            raise HTTPException(503, "No existe la base. Corre primero: python -m tradinglab descargar")
        return db.conectar_lectura(config.ruta_base)

    def serie_de(simbolo: str, intervalo: str, con_factores: bool = False) -> Serie:
        """Carga la serie, con caché mientras no lleguen velas nuevas."""
        con = conexion()
        try:
            ultima = db.ultima_ts(con, simbolo, intervalo)
            if ultima is None:
                raise HTTPException(404, f"No hay velas de {simbolo} {intervalo}")
            with candado:
                guardada = cache.get((simbolo, intervalo, con_factores))
            if guardada and guardada[0] == ultima:
                return guardada[1]
            serie = cargar_serie(con, simbolo, intervalo, con_factores)
            with candado:
                cache[(simbolo, intervalo, con_factores)] = (ultima, serie)
            return serie
        finally:
            con.close()

    @app.middleware("http")
    async def revalidar_archivos(request, call_next):  # type: ignore[no-untyped-def]
        """Que el navegador siempre pregunte si la página cambió (si no, tras una actualización
        sigue usando el app.js viejo). Si no cambió, el servidor responde 304 y no se baja de nuevo."""
        respuesta = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta

    @app.get("/", include_in_schema=False)
    def inicio() -> HTMLResponse:
        # Los archivos se piden con su fecha de modificación (?v=...): si cambian, el navegador
        # baja el nuevo en vez de usar el que tenía guardado.
        html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
        for archivo in ("app.js", "estilo.css"):
            version = int((ESTATICOS / archivo).stat().st_mtime)
            html = html.replace(f"/static/{archivo}", f"/static/{archivo}?v={version}")
        return HTMLResponse(html)

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    @app.get("/api/series")
    def series() -> list[dict[str, Any]]:
        con = conexion()
        try:
            filas = con.execute(
                "SELECT simbolo, intervalo, COUNT(*), MIN(ts), MAX(ts) FROM velas GROUP BY simbolo, intervalo"
            ).fetchall()
        finally:
            con.close()
        return [{"simbolo": s, "intervalo": i, "velas": n, "desde_ms": a, "hasta_ms": b} for s, i, n, a, b in filas]

    @app.get("/api/estrategias")
    def estrategias() -> list[dict[str, Any]]:
        return [
            {
                "nombre": e.nombre,
                "titulo": e.titulo,
                "descripcion": e.descripcion,
                "parametros": [
                    {"nombre": p.nombre, "tipo": p.tipo.__name__, "por_defecto": p.por_defecto,
                     "descripcion": p.descripcion, "rejilla": list(p.rejilla)}
                    for p in e.parametros
                ],
            }
            for e in ESTRATEGIAS.values()
        ]

    @app.get("/api/configuracion")
    def configuracion() -> dict[str, Any]:
        c = config.costos
        return {"comision": c.comision, "deslizamiento": c.deslizamiento,
                "deslizamiento_por_par": c.deslizamiento_por_par, "capital_inicial": c.capital_inicial,
                "max_velas": MAX_VELAS}

    @app.get("/api/backtest")
    def backtest(
        simbolo: str,
        intervalo: str = "1h",
        estrategia: str = "cruce_medias",
        parametros: str = "{}",
        desde: str | None = None,
        hasta: str | None = None,
        capital: float | None = None,
        fraccion: float = 1.0,
        comision: float | None = None,
        deslizamiento: float | None = None,
    ) -> dict[str, Any]:
        simbolo = simbolo.upper().replace("/", "")
        try:
            duracion_ms(intervalo)
            e = obtener(estrategia)
            completos = e.completar(json.loads(parametros or "{}"))
            base = config.costos.para(simbolo)
            costos = Costos(base.comision if comision is None else comision,
                            base.deslizamiento if deslizamiento is None else deslizamiento)
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(400, str(error)) from None
        capital = config.costos.capital_inicial if capital is None else capital
        serie = serie_de(simbolo, intervalo, bool(e.factores))
        inicio, fin = serie.rango(_fecha(desde), _fecha(hasta))
        if fin - inicio < 2:
            raise HTTPException(400, "La ventana tiene menos de 2 velas")
        if fin - inicio > MAX_VELAS:
            raise HTTPException(
                400,
                f"La ventana tiene {fin - inicio:,} velas y el panel muestra hasta {MAX_VELAS:,}. "
                "Acorta las fechas o usa el intervalo 1h.",
            )
        try:
            c = motor.backtest(serie, e, completos, int(serie.ts[inicio]), int(serie.ts[fin - 1]) + 1,
                               costos, capital, fraccion)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        r, bh = c.estrategia, c.comprar_y_mantener
        return {
            "simbolo": simbolo,
            "intervalo": intervalo,
            "estrategia": estrategia,
            "parametros": completos,
            "costos": {"comision": costos.comision, "deslizamiento": costos.deslizamiento},
            "velas": _velas(serie, inicio, fin),
            "marcas": [
                {"time": int(x.ts // 1000), "lado": x.lado, "precio": x.precio, "cantidad": x.cantidad,
                 "motivo": x.motivo}
                for x in r.ejecuciones
            ],
            "capital": _puntos(r.ts, r.capital, 2),
            "capital_bh": _puntos(bh.ts, bh.capital, 2),
            "drawdown": _puntos(r.ts, r.drawdown * 100, 3),
            "drawdown_bh": _puntos(bh.ts, bh.drawdown * 100, 3),
            "metricas": r.metricas.como_dict(),
            "referencias": {"comprar_y_mantener": bh.metricas.como_dict(), "no_operar": c.no_operar.como_dict()},
            "le_gana_a_no_operar": c.le_gana_a_no_operar,
            "le_gana_a_comprar_y_mantener": c.le_gana_a_comprar_y_mantener,
            "operaciones": [
                {"entrada": op.entrada_ts, "salida": op.salida_ts, "precio_entrada": op.precio_entrada,
                 "precio_salida": op.precio_salida, "ganancia": op.ganancia, "rendimiento": op.rendimiento}
                for op in r.operaciones
            ],
        }

    @app.get("/api/estudios")
    def estudios() -> list[dict[str, Any]]:
        con = conexion()
        try:
            lista = registro.listar_estudios(con)
        finally:
            con.close()
        for e in lista:
            e.pop("resumen", None)
        return lista

    @app.get("/api/estudios/{estudio_id}")
    def estudio(estudio_id: int) -> dict[str, Any]:
        con = conexion()
        try:
            e = registro.leer_estudio(con, estudio_id)
            if e is None:
                raise HTTPException(404, f"No existe el estudio #{estudio_id}")
            # Del walk-forward solo interesan las pruebas; el barrido se manda completo.
            muestra = "prueba" if e["tipo"] == "walk_forward" else None
            e["corridas"] = registro.leer_corridas(con, estudio_id, muestra)
        finally:
            con.close()
        return e

    @app.get("/api/papel")
    def papel() -> list[dict[str, Any]]:
        con = conexion()
        try:
            nombres = [f[0] for f in con.execute("SELECT nombre FROM papel_sesiones ORDER BY creada_ms DESC")]
            return [resumen_sesion(con, nombre) for nombre in nombres]
        finally:
            con.close()

    @app.get("/api/papel/{nombre}")
    def papel_sesion(nombre: str) -> dict[str, Any]:
        con = conexion()
        try:
            sesion = resumen_sesion(con, nombre)
            if sesion is None:
                raise HTTPException(404, f"No existe la sesión {nombre!r}")
            con.row_factory = sqlite3.Row
            operaciones = [dict(f) for f in con.execute(
                "SELECT ts, lado, precio, cantidad, comision, efectivo FROM papel_operaciones "
                "WHERE sesion = ? ORDER BY id", (nombre,))]
            capital = [dict(f) for f in con.execute(
                "SELECT ts, capital FROM papel_capital WHERE sesion = ? ORDER BY ts", (nombre,))]
            desde = sesion["creada_ms"] - 200 * duracion_ms(sesion["intervalo"])
            velas = con.execute(
                "SELECT ts, apertura, maximo, minimo, cierre FROM velas WHERE simbolo = ? AND intervalo = ? "
                "AND ts >= ? ORDER BY ts", (sesion["simbolo"], sesion["intervalo"], desde)).fetchall()
        finally:
            con.close()
        return {
            "sesion": sesion,
            "velas": [{"time": f[0] // 1000, "open": f[1], "high": f[2], "low": f[3], "close": f[4]} for f in velas],
            "marcas": [{"time": o["ts"] // 1000, "lado": o["lado"], "precio": o["precio"], "cantidad": o["cantidad"],
                        "motivo": "papel"} for o in operaciones],
            "operaciones": operaciones,
            "capital": [{"time": c["ts"] // 1000, "value": round(c["capital"], 2)} for c in capital],
        }

    return app
