# Plan de la fase 1: recolector de velas

Estado: **aprobado el 2026-11-20 tal como está (incluidas las cuatro decisiones de la sección 7)
e implementado ese mismo día.** Única diferencia con el plan: se agregó `tradinglab/tiempo.py`
para la duración de los intervalos y la conversión de fechas.

## 1. Fuente de datos: API REST pública de Binance, sin ccxt (recomendado)

- El endpoint `GET /api/v3/klines` devuelve 12 campos por vela. Además de OHLCV trae el volumen
  en USDT, el **número de operaciones** y el **volumen comprado por agresores (taker buy)**.
  ccxt solo entrega OHLCV y descarta el resto. Esos campos extra son justo las "operaciones y
  volúmenes" del bot original y no cuestan nada.
- Una sola dependencia (`requests`) en lugar de ccxt, que es un paquete grande.
- En contra: si algún día se quiere otro exchange, ccxt ayudaría. Por eso el cliente de Binance
  queda aislado en un solo módulo y se puede reemplazar.
- Respaldo: si `api.binance.com` falla o se bloquea, se usa `data-api.binance.vision`, que
  responde igual y solo sirve datos de mercado.

## 2. Estructura de carpetas

```
TradingLab/
├── CLAUDE.md
├── pyproject.toml            # metadatos y dependencias (requests; pytest en dev); Python >= 3.11
├── config.toml               # pares, intervalos, fecha de inicio, ruta de la base
├── docs/
│   ├── HISTORIAL.md
│   └── PLAN_FASE1.md
├── tradinglab/               # paquete principal
│   ├── __init__.py
│   ├── __main__.py           # línea de comandos: python -m tradinglab <comando>
│   ├── config.py             # lee config.toml
│   ├── db.py                 # conexión a SQLite y creación del esquema
│   └── recolector/
│       ├── __init__.py
│       ├── binance.py        # cliente REST público: velas, hora del servidor, límites de peso
│       ├── descarga.py       # descarga incremental por serie (par + intervalo)
│       └── verificacion.py   # conteos, huecos, velas inválidas, cruce 5m contra 1h
├── tests/
│   ├── test_db.py
│   ├── test_descarga.py      # con respuestas de Binance simuladas, sin red
│   └── test_verificacion.py
├── datos/                    # ignorado por git
│   └── tradinglab.sqlite
└── .venv/                    # ignorado por git
```

Las fases siguientes agregan `tradinglab/backtest/`, `tradinglab/validacion/`,
`tradinglab/panel/` y `tradinglab/papel/`.

## 3. Esquema de la tabla de velas

```sql
CREATE TABLE IF NOT EXISTS velas (
    simbolo               TEXT    NOT NULL,  -- 'BTCUSDT', con el nombre de Binance
    intervalo             TEXT    NOT NULL,  -- '5m', '1h'
    ts                    INTEGER NOT NULL,  -- apertura de la vela, ms desde epoch, UTC
    apertura              REAL    NOT NULL,
    maximo                REAL    NOT NULL,
    minimo                REAL    NOT NULL,
    cierre                REAL    NOT NULL,
    volumen               REAL    NOT NULL,  -- en la moneda base (BTC, ETH, ZEC)
    volumen_cotizado      REAL    NOT NULL,  -- en la moneda de cotización (USDT)
    operaciones           INTEGER NOT NULL,  -- número de operaciones dentro de la vela
    compra_taker          REAL    NOT NULL,  -- volumen base comprado por agresores
    compra_taker_cotizado REAL    NOT NULL,  -- lo mismo, en USDT
    PRIMARY KEY (simbolo, intervalo, ts)
) WITHOUT ROWID;
```

- La **llave primaria** `(simbolo, intervalo, ts)` hace imposible guardar una vela dos veces.
- `WITHOUT ROWID` guarda las filas ordenadas por esa llave: leer una serie por rango de fechas
  es rápido sin índices extra.
- No se guarda la hora de cierre (es `ts` + duración − 1 ms) ni el campo 12 de Binance, que no
  se usa.
- Los precios se guardan como `REAL` (doble precisión, unos 15 dígitos significativos):
  suficiente para investigación con los 8 decimales que publica Binance.
- La versión del esquema se lleva con `PRAGMA user_version`, sin tabla extra.
- La base se abre en modo `WAL`, para que el panel web pueda leer mientras el recolector escribe.

## 4. Cómo se descarga el historial

Para cada serie (par + intervalo):

1. **Punto de partida**: `SELECT MAX(ts)` de esa serie. Si no hay nada, se empieza en
   2020-01-01 00:00 UTC; si hay, en la última vela guardada más la duración del intervalo.
2. **Petición**: `GET /api/v3/klines?symbol=…&interval=…&startTime=…&limit=1000`.
3. **Solo velas cerradas**: se descarta la vela que todavía se está formando (la que cierra
   después de la hora del servidor, que se obtiene con `GET /api/v3/time`).
4. **Guardado por lotes**: cada lote de hasta 1000 velas se inserta con `INSERT OR IGNORE`
   dentro de una transacción, con commit por lote. Si se va la luz o internet, se pierde como
   mucho el lote en curso y la siguiente corrida reanuda desde la última vela guardada.
5. **Avance**: `startTime` pasa a la última vela recibida más un intervalo, hasta llegar a la
   vela actual.
6. **Límites de la API**: cada petición de velas pesa 2, de un máximo de 6000 por minuto. Se lee
   el encabezado `X-MBX-USED-WEIGHT-1M` y, si pasa del 80%, se espera al siguiente minuto. Con un
   error 429 se respeta `Retry-After`; con un 418 (bloqueo de IP) se detiene y avisa. Los errores
   de red se reintentan con espera creciente. Con una pausa breve entre peticiones se usa
   alrededor del 10% del límite.
7. **Huecos**: Binance no publica velas durante sus mantenimientos y caídas. No se rellenan con
   velas inventadas: `verificar` los lista y el motor de backtest (fase 2) los tendrá en cuenta.

**Tamaño estimado** (2020-01-01 a hoy): unas 724 mil velas de 5m y 60 mil de 1h por par; unos
2.35 millones de filas en total, unas 2,400 peticiones, **unos 10 minutos la primera vez** y una
base de 250 a 300 MB. Las corridas siguientes tardan segundos.

## 5. Comandos

```powershell
python -m tradinglab descargar                                  # todos los pares e intervalos de config.toml
python -m tradinglab descargar --simbolo ZECUSDT --intervalo 1h # una sola serie
python -m tradinglab verificar                                  # resumen y control de calidad
```

`verificar` muestra por serie: primera y última vela, total de velas, huecos (con fechas),
velas inválidas (por ejemplo, un máximo menor que el cierre) y un **cruce de 5m contra 1h**: se
juntan 12 velas de 5m y se comparan con la vela de 1h que publica Binance (apertura, máximo,
mínimo, cierre y volumen deben coincidir).

Para mantener la base al día basta con correr `descargar` cada cierto tiempo (Programador de
tareas de Windows ahora; cron o systemd en un servidor). Los datos al segundo llegan en la fase 5
por websocket.

## 6. Pruebas

- Con pytest y respuestas simuladas, sin red: reanuda donde se quedó, correr dos veces no
  duplica nada, descarta la vela abierta, maneja los errores 429 y 418, y la verificación
  detecta huecos y velas inválidas.
- Una corrida real: descarga completa, segunda corrida que debe insertar 0 velas, y `verificar`.

## 7. Decisiones que necesitan visto bueno

1. API directa de Binance (recomendado) o ccxt.
2. Columnas en español (`apertura`, `maximo`, `minimo`, `cierre`) o en inglés (`open`, `high`,
   `low`, `close`).
3. Inicio del historial: 2020-01-01 00:00 UTC.
4. Los principios 6 y 7 que agregó Claude en CLAUDE.md: sin información del futuro y
   reproducibilidad.
