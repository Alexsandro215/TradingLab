import pytest

from tradinglab import db
from tradinglab.recolector.descarga import kline_a_fila

from fabrica import CINCO_MIN, T0, serie


def filas(cantidad: int) -> list[tuple]:
    return [kline_a_fila("BTCUSDT", "5m", k) for k in serie(T0, cantidad, CINCO_MIN)]


def test_crea_esquema_y_version(tmp_path):
    ruta = tmp_path / "sub" / "prueba.sqlite"
    con = db.conectar(ruta)
    assert ruta.exists()
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.VERSION_ESQUEMA
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    columnas = [fila[1] for fila in con.execute("PRAGMA table_info(velas)")]
    assert tuple(columnas) == db.COLUMNAS_VELAS
    con.close()
    # Reabrir no falla ni borra nada.
    db.conectar(ruta).close()


def test_rechaza_esquema_mas_nuevo(tmp_path):
    ruta = tmp_path / "prueba.sqlite"
    con = db.conectar(ruta)
    con.execute(f"PRAGMA user_version = {db.VERSION_ESQUEMA + 1}")
    con.close()
    with pytest.raises(RuntimeError):
        db.conectar(ruta)


def test_insertar_no_duplica():
    con = db.conectar(":memory:")
    assert db.insertar_velas(con, filas(5)) == 5
    assert db.insertar_velas(con, filas(5)) == 0
    assert db.insertar_velas(con, filas(8)) == 3
    assert db.insertar_velas(con, []) == 0
    assert con.execute("SELECT COUNT(*) FROM velas").fetchone()[0] == 8


def test_ultima_ts():
    con = db.conectar(":memory:")
    assert db.ultima_ts(con, "BTCUSDT", "5m") is None
    db.insertar_velas(con, filas(4))
    assert db.ultima_ts(con, "BTCUSDT", "5m") == T0 + 3 * CINCO_MIN
    assert db.ultima_ts(con, "BTCUSDT", "1h") is None
    assert db.ultima_ts(con, "ETHUSDT", "5m") is None
