"""Registro de estudios y corridas en SQLite (principio 7: reproducibilidad).

Cada estudio guarda su configuración completa, cuántas simulaciones corrió (para medir el
riesgo de sobreajuste), la versión del código (commit de git) y hasta qué vela había datos.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from typing import Any

from tradinglab.backtest.estrategias import texto_parametros
from tradinglab.backtest.motor import Metricas
from tradinglab.config import RAIZ

COLUMNAS_CORRIDA = (
    "simbolo", "intervalo", "estrategia", "parametros", "ventana", "muestra", "desde_ms", "hasta_ms",
    "rendimiento", "drawdown_maximo", "operaciones", "comisiones", "ganadoras", "exposicion",
    "bh_rendimiento", "bh_drawdown",
)


def version_codigo() -> str | None:
    """Commit actual de git; termina en '+cambios' si hay cambios sin commit. None si no hay git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True, timeout=10
        )
        if commit.returncode != 0:
            return None
        estado = subprocess.run(
            ["git", "status", "--porcelain"], cwd=RAIZ, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return commit.stdout.strip() + ("+cambios" if estado.stdout.strip() else "")


def fila_corrida(
    simbolo: str,
    intervalo: str,
    estrategia: str,
    parametros: dict[str, Any],
    ventana: str,
    muestra: str,
    desde_ms: int,
    hasta_ms: int,
    metricas: Metricas,
    bh: Metricas,
) -> dict[str, Any]:
    return {
        "simbolo": simbolo,
        "intervalo": intervalo,
        "estrategia": estrategia,
        "parametros": texto_parametros(parametros),
        "ventana": ventana,
        "muestra": muestra,
        "desde_ms": int(desde_ms),
        "hasta_ms": int(hasta_ms),
        "rendimiento": metricas.rendimiento,
        "drawdown_maximo": metricas.drawdown_maximo,
        "operaciones": metricas.operaciones,
        "comisiones": metricas.comisiones,
        "ganadoras": metricas.ganadoras,
        "exposicion": metricas.exposicion,
        "bh_rendimiento": bh.rendimiento,
        "bh_drawdown": bh.drawdown_maximo,
    }


def guardar_estudio(
    con: sqlite3.Connection,
    tipo: str,
    descripcion: str,
    configuracion: dict[str, Any],
    corridas: list[dict[str, Any]],
    resumen: Any,
    combinaciones: int,
    datos_hasta_ms: int | None,
    commit_git: str | None = None,
) -> int:
    """Guarda el estudio y todas sus corridas en una sola transacción. Devuelve su id.

    `commit_git` debe tomarse con version_codigo() al EMPEZAR el estudio: es el código que se
    cargó. Si no se da, se calcula ahora.
    """
    if commit_git is None:
        commit_git = version_codigo()
    columnas = ", ".join(COLUMNAS_CORRIDA)
    marcas = ", ".join("?" * (len(COLUMNAS_CORRIDA) + 1))
    with con:
        cursor = con.execute(
            "INSERT INTO estudios (creado_ms, tipo, descripcion, configuracion, combinaciones, commit_git, "
            "datos_hasta_ms, resumen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(time.time() * 1000), tipo, descripcion,
                json.dumps(configuracion, ensure_ascii=False, sort_keys=True),
                combinaciones, commit_git, datos_hasta_ms,
                json.dumps(resumen, ensure_ascii=False),
            ),
        )
        estudio_id = int(cursor.lastrowid)
        con.executemany(
            f"INSERT INTO corridas (estudio_id, {columnas}) VALUES ({marcas})",
            [(estudio_id, *(c[k] for k in COLUMNAS_CORRIDA)) for c in corridas],
        )
    return estudio_id


def _estudio_desde_fila(fila: sqlite3.Row) -> dict[str, Any]:
    estudio = dict(fila)
    estudio["configuracion"] = json.loads(estudio["configuracion"])
    estudio["resumen"] = json.loads(estudio["resumen"]) if estudio["resumen"] else None
    return estudio


def listar_estudios(con: sqlite3.Connection, limite: int = 100) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    try:
        filas = con.execute(
            "SELECT e.*, (SELECT COUNT(*) FROM corridas c WHERE c.estudio_id = e.id) AS corridas "
            "FROM estudios e ORDER BY e.id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    finally:
        con.row_factory = None
    return [_estudio_desde_fila(f) for f in filas]


def leer_estudio(con: sqlite3.Connection, estudio_id: int) -> dict[str, Any] | None:
    con.row_factory = sqlite3.Row
    try:
        fila = con.execute("SELECT * FROM estudios WHERE id = ?", (estudio_id,)).fetchone()
    finally:
        con.row_factory = None
    return _estudio_desde_fila(fila) if fila else None


def leer_corridas(con: sqlite3.Connection, estudio_id: int, muestra: str | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT id, {', '.join(COLUMNAS_CORRIDA)} FROM corridas WHERE estudio_id = ?"
    argumentos: list[Any] = [estudio_id]
    if muestra:
        sql += " AND muestra = ?"
        argumentos.append(muestra)
    con.row_factory = sqlite3.Row
    try:
        filas = con.execute(sql + " ORDER BY id", argumentos).fetchall()
    finally:
        con.row_factory = None
    corridas = []
    for f in filas:
        corrida = dict(f)
        corrida["parametros"] = json.loads(corrida["parametros"])
        corridas.append(corrida)
    return corridas
