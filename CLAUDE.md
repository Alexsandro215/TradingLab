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

| # | Fase                                                                   | Estado                                                        |
| - | ---------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1 | Recolector de velas hacia SQLite                                       | Hecha el 2026-11-20 ([docs/PLAN_FASE1.md](docs/PLAN_FASE1.md)) |
| 2 | Motor de backtest con costos reales y las dos referencias              | Hecha el 2026-11-20                                           |
| 3 | Validación fuera de muestra y corridas masivas por línea de comandos | Hecha el 2026-11-20 ([docs/RESULTADOS.md](docs/RESULTADOS.md)) |
| 4 | Panel web                                                              | Hecha el 2026-11-20                                           |
| 5 | Operación en papel con datos en vivo                                  | Hecha el 2026-11-20 (probada en vivo 3 minutos)               |
| 6 | Factores externos y estudio de eventos                                 | Hecha el 2026-11-20 (la pidió el usuario después del plan)    |

Los hallazgos de la investigación se anotan en [docs/RESULTADOS.md](docs/RESULTADOS.md) (lo más
reciente arriba). Antes de proponer estrategias o estudios nuevos, léelo.

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
6. **Factores externos**: funding e interés abierto de los futuros, índice de miedo y codicia, y
   flujo de órdenes. Un estudio de eventos mide si avisan ANTES de las caídas fuertes, y hay
   estrategias que los usan como filtro. Las noticias quedan para después: hay poca historia
   gratuita, y si un modelo de IA califica noticias viejas, ya sabe qué pasó después (eso
   contamina el backtest). Solo se usarían hacia adelante.

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
- **Pares reservados para validación** (`simbolos_validacion` en `config.toml`, solo en 1h): se
  descargan con todo lo demás, pero barrido, walk-forward y eventos no los usan por defecto.
  Sirven para confirmar hipótesis registradas de antemano en `docs/RESULTADOS.md`. **Todos están
  gastados**: SOL, BNB y XRP (H1, H2b y H3) y ADA, LTC y LINK (H4). Para una hipótesis nueva hay
  que reservar pares nuevos ANTES de explorar, por ejemplo DOGE, AVAX o DOT (verificar que
  existan desde 2020).
- **Factores** (fase 6, comando `factores`):
  - funding de los futuros perpetuos USDT-M de Binance, cada 8 h, desde 2020 en los 6 pares;
  - métricas de futuros cada 5 minutos (interés abierto y proporciones de largos y cortos) desde
    `data.binance.vision`: BTC desde 2020-09, el resto desde finales de 2021 o después. Se
    publican al día siguiente, así que no sirven en vivo;
  - índice de miedo y codicia diario de alternative.me, desde 2018. Se usa el del día anterior,
    porque el de hoy se publica a una hora desconocida.
  Cada factor se alinea con la vela tomando el último valor conocido al cierre de la vela; si es
  demasiado viejo, queda vacío (`factores/tabla.py`).

## Reglas de la simulación

Las aplican igual el motor de backtest (`backtest/motor.py`) y la operación en papel
(`papel/operador.py`). Una prueba verifica que, con las mismas velas, el papel haga exactamente
las mismas operaciones que el backtest.

- Solo posiciones largas (spot). Al entrar se invierte `fraccion` del capital (1 = todo); al
  salir se vende todo.
- **Posiciones parciales**: si la estrategia es `fraccional`, su objetivo es la fracción del
  capital a tener invertida (0 a 1). Solo se rebalancea cuando la diferencia pasa de 10 puntos
  (`BANDA_REBALANCEO`), y salir del todo siempre se ejecuta. Cada venta, total o parcial, es una
  operación, y su ganancia se mide contra el costo promedio. La operación en papel todavía solo
  hace todo o nada.
- Métricas de riesgo además de las mínimas: rendimiento anual compuesto y **Calmar** =
  rendimiento anual / |drawdown máximo|.
- La estrategia da una posición objetivo (0 o 1) al cierre de cada vela; se ejecuta en la
  apertura de la siguiente vela **con operaciones**. En velas sin operaciones no se ejecuta nada.
- Costos por lado: comisión de 0.1% y deslizamiento de 0.05% (0.2% en ZEC), en `config.toml`.
- Al final de cada ventana se vende al cierre de la última vela, pagando costos.
- Comprar y mantener usa el mismo motor y los mismos costos: compra al abrir la ventana y vende
  al cerrarla.
- "Le gana" significa mayor rendimiento neto en la misma ventana. El drawdown se reporta siempre
  junto al rendimiento.
- En papel, si el programa se conecta a mitad de una vela, ejecuta al precio del momento y no a la
  apertura, porque esa apertura ya pasó.
- Las estrategias que usan factores (`Estrategia.factores`) reciben las columnas de
  `factores/tabla.py`. La operación en papel todavía no las acepta, porque no recibe esos
  factores en vivo.
- Las estrategias calculan sus indicadores sobre todo el historial. Sus indicadores solo miran
  hacia atrás, y hay una prueba que lo verifica para cada estrategia.

## Stack

- **Python 3.11 o más nuevo.** Localmente hay Python 3.14 (Windows 11), pero el código debe
  funcionar en 3.11 porque un servidor Debian 12 trae esa versión.
- **Entorno virtual** en `.venv/` dentro del proyecto.
- **SQLite** con el módulo `sqlite3` de la biblioteca estándar.
- **Configuración** en `config.toml`, leída con `tomllib` (biblioteca estándar).
- **Descarga**: `requests` contra la API REST pública de Binance, sin ccxt, para conservar el
  número de operaciones y el volumen taker de cada vela.
- **Análisis y backtest**: pandas y numpy (fase 2). El motor solo recorre los puntos donde
  cambia la posición: un backtest de 1h tarda ~0.02 s y uno de 5m completo ~0.5 s.
- **Panel web**: FastAPI, uvicorn y TradingView Lightweight Charts 4.2.3 (fase 4), en JavaScript
  sin compilar.
- **Datos en vivo**: `websockets` contra el websocket público de Binance (fase 5); respaldo
  `data-stream.binance.vision`.
- **Pruebas**: pytest (y httpx para el cliente de pruebas de FastAPI).

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
- **Estrategias nuevas**: van en `backtest/estrategias.py` con pocos parámetros, una rejilla
  pequeña y una validación. La prueba `test_estrategias_no_ven_el_futuro` las cubre solas.
- **Estudios**: corre barridos y walk-forward con el código ya en commit, para que el estudio
  quede atado a una versión exacta. Si el commit termina en `+cambios`, el código tenía cambios
  sin commit cuando se corrió. El commit se toma al EMPEZAR cada estudio.
- **Hipótesis antes que resultados**: cualquier prueba de confirmación (pares reservados,
  filtros nuevos) se escribe en `docs/RESULTADOS.md`, con su criterio de éxito, ANTES de
  correrla, y se reporta tal cual salga.

## Estructura

```
config.toml                 pares, intervalos, fecha de inicio, base, URLs, costos, puerto del panel
pyproject.toml              dependencias; Python >= 3.11
tradinglab/
  __main__.py               lectura de argumentos: python -m tradinglab <comando>
  comandos.py               cada comando (imprime en la terminal)
  reporte.py                formato de tablas y porcentajes para la terminal
  config.py                 lee config.toml
  db.py                     conexión a SQLite y esquema (velas, estudios, corridas, papel_*)
  tiempo.py                 duración de intervalos y conversión de fechas (UTC, ms)
  recolector/               fase 1
    binance.py              cliente REST público: reintentos, límites de peso, URL de respaldo
    descarga.py             descarga incremental por serie
    verificacion.py         huecos, velas inválidas, cruce 5m contra 1h
  backtest/                 fase 2
    costos.py               comisión y deslizamiento (compartido con papel)
    datos.py                carga de una serie desde SQLite
    estrategias.py          catálogo con sus rejillas: cruce_medias, ruptura, rsi, momentum;
                            con factores: momentum_apalancamiento, momentum_sentimiento;
                            de riesgo: tendencia_larga, volatilidad_objetivo, tendencia_volatilidad
    motor.py                simulación, métricas y las dos referencias
  validacion/               fase 3
    ventanas.py             ventanas de calendario y pliegues de walk-forward
    barrido.py              corridas masivas (todo dentro de muestra)
    walk_forward.py         validación fuera de muestra
    registro.py             guarda estudios y corridas con el commit de git
  panel/                    fase 4
    app.py                  FastAPI (solo lectura, 127.0.0.1)
    static/                 index.html, app.js, estilo.css (Lightweight Charts 4.2.3 desde unpkg)
  papel/                    fase 5
    operador.py             estado de la sesión y ejecución de órdenes simuladas
    en_vivo.py              websocket de Binance y relleno por REST al (re)conectar
  factores/                 fase 6
    descarga.py             funding (API de futuros), métricas (data.binance.vision), miedo y codicia
    tabla.py                factores alineados con cada vela, sin ver el futuro
    eventos.py              estudio de eventos: ¿qué factor avisa antes de las caídas?
tests/                      pytest, sin red (fabrica.py simula a Binance)
analisis/                   exploraciones sueltas y reproducibles (adelanto.py: ¿un mercado se adelanta a otro?)
docs/                       HISTORIAL.md, RESULTADOS.md, PLAN_FASE1.md
datos/tradinglab.sqlite     la base (ignorada por git)
datos/externos/             series externas (FRED: S&P 500, Nasdaq, dólar), ignoradas por git
```

Tablas de la base (esquema v3, en `PRAGMA user_version`):
- `velas`: llave primaria `(simbolo, intervalo, ts)`; columnas `apertura, maximo, minimo, cierre,
  volumen, volumen_cotizado, operaciones, compra_taker, compra_taker_cotizado`.
- `estudios` y `corridas`: cada barrido, walk-forward o backtest guardado, con su configuración,
  número de simulaciones y commit de git. En las corridas, `muestra` es `completa`,
  `entrenamiento` o `prueba`.
- `papel_sesiones`, `papel_operaciones`, `papel_capital`: estado de la operación en papel.
- `funding`, `metricas_futuros`, `miedo_codicia`: factores externos (fase 6), cada uno con el
  instante en que se conoció.

Los cambios de esquema hasta ahora solo agregan tablas (`CREATE TABLE IF NOT EXISTS`). Si algún
día hay que cambiar una tabla existente, sube `db.VERSION_ESQUEMA` y escribe la migración.

## Comandos

Crear el entorno (una sola vez):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Con el entorno activado:

```powershell
python -m pytest                                        # pruebas (71, sin red, ~4 s)
python -m tradinglab --help                             # todos los comandos

# Fase 1: datos
python -m tradinglab descargar                          # baja o actualiza todo lo de config.toml
python -m tradinglab descargar --simbolo ZECUSDT --intervalo 1h   # una sola serie
python -m tradinglab verificar                          # resumen y control de calidad

# Fase 2: un backtest contra las dos referencias
python -m tradinglab estrategias                        # estrategias, parámetros y rejillas
python -m tradinglab backtest --simbolo ETHUSDT --intervalo 1h --estrategia momentum --param ventana=168
python -m tradinglab backtest --simbolo BTCUSDT --estrategia cruce_medias --desde 2022-01-01 --hasta 2023-01-01 --operaciones 10

# Fase 3: corridas masivas y validación fuera de muestra (se guardan como estudios)
python -m tradinglab barrido                            # todas las estrategias, pares, intervalos y ventanas (~2 min)
python -m tradinglab barrido --estrategia rsi --intervalo 1h --ventanas anual
python -m tradinglab walk-forward                       # 12 meses entrenamiento / 3 prueba (~2.5 min)
python -m tradinglab walk-forward --intervalo 1h --entrenamiento 24 --prueba 6 --criterio calmar --detalle
python -m tradinglab estudios                           # lista; `estudios 2` muestra uno

# Fase 4: panel web en http://127.0.0.1:8000 (#estudios, #estudios/2 y #papel abren esas pestañas)
python -m tradinglab panel --abrir

# Fase 5: operación en papel (Ctrl+C para detener; se retoma con el mismo --nombre)
python -m tradinglab papel --simbolo ETHUSDT --intervalo 1h --estrategia momentum --param ventana=168
python -m tradinglab papel --nombre ETHUSDT-1h-momentum  # retomar
python -m tradinglab papel --listar

# Fase 6: factores externos
python -m tradinglab factores                           # descarga incremental (la primera vez, ~30 min)
python -m tradinglab eventos                            # ¿qué factor avisa antes de las caídas? (BTC, ETH, ZEC 1h)
python -m tradinglab eventos --simbolo ETHUSDT --horizonte 12 --corte 2023-07-01
python -m tradinglab walk-forward --estrategia momentum_apalancamiento --intervalo 1h

# Gestión de riesgo (posiciones parciales): elegir por Calmar
python -m tradinglab walk-forward --estrategia tendencia_volatilidad --intervalo 1h --criterio calmar
```

- `descargar` es incremental: se puede interrumpir y volver a correr cuando sea.
- `verificar` devuelve código 1 si hay velas inválidas o diferencias entre 5m y 1h; los huecos
  solos no cuentan como error.
- El panel no muestra más de 150,000 velas por consulta: 5m solo cabe en ventanas de hasta
  un año y medio.
- `papel` rellena por REST lo que falte antes de conectarse y después de cada desconexión. Si
  la PC se suspende, la sesión se queda quieta hasta que se vuelva a correr.
- Para dejar una sesión de papel corriendo sin ventana, independiente de la terminal (así se
  lanzó la de ETH; el número de proceso queda en `datos/*.pid` y el registro en `datos/*.log`):
  ```powershell
  Start-Process .venv\Scripts\python.exe -ArgumentList "-m tradinglab papel --nombre ETHUSDT-1h-momentum" -WindowStyle Hidden -RedirectStandardError datos\papel-ETHUSDT-1h-momentum.log
  ```
