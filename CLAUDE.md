# TradingLab

Laboratorio de investigación de estrategias de trading algorítmico sobre criptomonedas
(BTC, ETH y ZEC contra USDT en Binance). **No es una máquina de dinero: aquí no se opera con
dinero real.** La pregunta que queremos responder, con evidencia y con costos reales, es si
alguna estrategia le gana a no operar y a comprar y mantener.

## Regla de cada sesión: el historial

1. **Al empezar la sesión**, lee [docs/HISTORIAL.md](docs/HISTORIAL.md) antes de hacer cualquier
   otra cosa. Ahí está qué se decidió, qué se hizo y qué quedó pendiente. Las entradas van de la
   más reciente (arriba) a la más antigua.
2. **Al terminar la sesión** (o al cerrar un bloque de trabajo importante), agrega una entrada
   nueva **arriba de todas** en `docs/HISTORIAL.md` con la fecha (AAAA-MM-DD) y tres apartados:
   *Decisiones*, *Lo que se hizo* y *Pendiente*.
3. Si una decisión cambia algo de este archivo (principios, fases, stack o convenciones),
   actualiza también este archivo en la misma sesión.

## De dónde sale la idea

En Facebook se publicó el ensayo de un bot autónomo de trading: Python 3.11 en Debian 12, con
panel web, que recolecta operaciones y volúmenes desde 2020 en SQLite y corre 24 horas. Estudiaba
BTC, ETH y ZEC. En 3 días corrió unas 800 simulaciones por línea de comandos (ventanas desde 2020
hasta hoy y ventanas intermedias) con 4 variantes de estrategia, de conservadora a "kamikaze".
Su conclusión: **nada le ganó a no operar.** Este proyecto repite esa pregunta con rigor.

## Alcance y límites

- **Sin dinero real.** El proyecto solo usa datos públicos y no necesita llaves de API. No se
  escribe código que envíe órdenes a un exchange, ni siquiera desactivado.
- Conectarlo algún día a dinero real es decisión exclusiva del usuario y **queda fuera del
  alcance de este proyecto**.
- La operación en papel (fase 5) simula las órdenes localmente con datos en vivo.

## Principios

1. **Costos reales en toda simulación**: comisión de 0.1% por lado (tarifa spot de Binance) y
   un deslizamiento de precio por lado. Ningún resultado sin costos se presenta como resultado.
2. **Dos referencias siempre**: toda estrategia se compara contra *no operar* (el capital se
   queda igual) y contra *comprar y mantener* (compra al inicio de la ventana y vende al final,
   pagando los mismos costos), en la misma ventana y con el mismo capital inicial.
3. **Validación fuera de muestra (walk-forward)**: los parámetros se eligen en un periodo y se
   prueban en el periodo siguiente, que la estrategia no vio. Solo los resultados fuera de
   muestra cuentan como evidencia.
4. **Cuidado con el sobreajuste**: cada estudio registra cuántas combinaciones se probaron. El
   mejor resultado entre muchos intentos es sospechoso por defecto; se prefieren estrategias con
   pocos parámetros y resultados estables en ventanas vecinas.
5. **Métricas mínimas** de cada corrida: rendimiento neto, drawdown máximo, número de
   operaciones, comisiones pagadas y porcentaje de operaciones ganadoras.
6. **Sin información del futuro**: una decisión solo usa velas ya cerradas; la orden se ejecuta
   al precio de apertura de la vela siguiente, más el deslizamiento.
7. **Reproducibilidad**: cada corrida guarda sus parámetros, la ventana, los costos y el commit
   de git, para poder repetirla y obtener lo mismo.

Los principios 6 y 7 los propuso Claude en el arranque y el usuario los aprobó el 2026-11-20.

## Fases

| # | Fase | Estado |
|---|------|--------|
| 1 | Recolector de velas hacia SQLite | Hecha el 2026-11-20 ([docs/PLAN_FASE1.md](docs/PLAN_FASE1.md)) |
| 2 | Motor de backtest con costos reales y las dos referencias | Pendiente |
| 3 | Validación fuera de muestra y corridas masivas por línea de comandos | Pendiente |
| 4 | Panel web | Pendiente |
| 5 | Operación en papel con datos en vivo | Pendiente |

1. **Recolector**: velas OHLCV de BTC/USDT, ETH/USDT y ZEC/USDT desde 2020-01-01, en 5m y 1h
   para empezar, desde la API pública de Binance (sin llaves) hacia SQLite. Descarga incremental
   (reanuda donde se quedó) y sin duplicados.
2. **Motor de backtest**: simula una estrategia sobre las velas cobrando comisión y
   deslizamiento, y reporta las métricas mínimas junto a las dos referencias.
3. **Validación y corridas masivas**: walk-forward, ventanas desde 2020 hasta hoy y ventanas
   intermedias, muchas combinaciones desde la línea de comandos, con registro de todo lo probado.
4. **Panel web**: FastAPI con TradingView Lightweight Charts; operaciones marcadas sobre las
   velas, curva de capital y drawdown.
5. **Operación en papel**: datos en vivo por websocket y órdenes simuladas, sin dinero real.

## Datos

- Fuente: Binance spot, API REST pública (`api.binance.com`; respaldo:
  `data-api.binance.vision`, que solo sirve datos de mercado).
- Pares: `BTCUSDT`, `ETHUSDT`, `ZECUSDT`. Verificado el 2026-11-20: los tres en estado TRADING;
  BTC y ETH con velas desde 2017-08-17 y ZEC desde 2019-03-21.
- Intervalos: `5m` y `1h`, desde 2020-01-01 00:00 UTC.
- Límite de la API: 6000 de peso por minuto por IP; cada petición de velas pesa 2.
- **Huecos**: hay 15 huecos, los mismos en los tres pares (mantenimientos de todo Binance), que
  suman 466 velas de 5m, unas 39 horas. El más grande es el del 2020-02-19, de casi 6 horas. El
  backtest no debe suponer que las velas son continuas.
- **Velas sin operaciones** (`operaciones = 0`): Binance las llena con el cierre anterior y
  volumen 0. ZEC tiene 2,951 de 5m (0.4%); BTC y ETH, 31 cada uno. En esas velas no hubo
  precio real al cual operar: el backtest no debe llenar órdenes ahí como si hubiera liquidez.

## Stack

- **Python 3.11 o más nuevo.** Localmente hay Python 3.14 (Windows 11), pero el código debe
  funcionar en 3.11 porque un servidor Debian 12 trae esa versión.
- **Entorno virtual** en `.venv/` dentro del proyecto.
- **SQLite** con el módulo `sqlite3` de la biblioteca estándar.
- **Configuración** en `config.toml`, leída con `tomllib` (biblioteca estándar).
- **Descarga**: `requests` contra la API REST pública de Binance, sin ccxt, para conservar el
  número de operaciones y el volumen taker de cada vela.
- **Análisis y backtest**: pandas y numpy (fase 2).
- **Panel web**: FastAPI, uvicorn y TradingView Lightweight Charts (fase 4).
- **Datos en vivo**: websockets públicos de Binance (fase 5).
- **Pruebas**: pytest.

## Convenciones

- **Idioma**: español en documentación, comentarios, docstrings, mensajes de la línea de
  comandos y mensajes de commit. Los nombres de variables, funciones y columnas también van en
  español, sin acentos ni ñ (`descargar_velas`, `maximo`). Se conservan en inglés los términos
  técnicos sin buena traducción (`backtest`, `drawdown`, `walk_forward`, `taker`).
- **Tiempo**: todo en UTC. Los instantes se guardan como enteros en milisegundos desde epoch,
  igual que Binance. La conversión a fecha legible o a hora local se hace solo al mostrar.
- **Velas**: el campo `ts` es la apertura de la vela. Solo se guardan velas ya cerradas. Los
  huecos (mantenimientos de Binance) no se rellenan con velas inventadas: se reportan.
- **Portabilidad**: rutas con `pathlib`, relativas a la raíz del proyecto; nada de rutas fijas de
  Windows, para poder mover el proyecto a un servidor Linux.
- **Datos fuera de git**: la base SQLite y todo lo descargado va en `datos/`, que git ignora.
- **Sin secretos**: nunca se guardan llaves, contraseñas ni archivos `.env` en el repositorio.
- **Dependencias mínimas**, declaradas en `pyproject.toml`.
- **Pruebas sin red**: las pruebas usan respuestas de Binance simuladas.

## Estructura

```
config.toml                 pares, intervalos, fecha de inicio, ruta de la base, URLs de Binance
pyproject.toml              dependencias; Python >= 3.11
tradinglab/
  __main__.py               línea de comandos: python -m tradinglab <comando>
  config.py                 lee config.toml
  db.py                     conexión a SQLite, esquema (tabla velas) e inserción sin duplicados
  tiempo.py                 duración de intervalos y conversión de fechas (UTC, ms)
  recolector/
    binance.py              cliente REST público: reintentos, límites de peso, URL de respaldo
    descarga.py             descarga incremental por serie
    verificacion.py         huecos, velas inválidas, cruce 5m contra 1h
tests/                      pytest, sin red (fabrica.py simula a Binance)
datos/tradinglab.sqlite     la base (ignorada por git)
```

La tabla `velas` tiene llave primaria `(simbolo, intervalo, ts)` y columnas `apertura, maximo,
minimo, cierre, volumen, volumen_cotizado, operaciones, compra_taker, compra_taker_cotizado`.
La versión del esquema está en `PRAGMA user_version` (`db.VERSION_ESQUEMA`).

## Comandos

Crear el entorno (una sola vez):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Con el entorno activado:

```powershell
python -m pytest                                        # pruebas
python -m tradinglab descargar                          # baja o actualiza todo lo de config.toml
python -m tradinglab descargar --simbolo ZECUSDT --intervalo 1h   # una sola serie
python -m tradinglab verificar                          # resumen y control de calidad
python -m tradinglab verificar --simbolo BTCUSDT --max-huecos 20
```

`descargar` es incremental: se puede interrumpir y volver a correr cuando sea. `verificar`
devuelve código 1 si hay velas inválidas o diferencias entre 5m y 1h; los huecos solos no
cuentan como error.
