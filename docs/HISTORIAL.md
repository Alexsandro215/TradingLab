# Historial del proyecto

Bitácora de TradingLab. Al empezar cada sesión se lee este archivo; al terminarla se agrega una
entrada **arriba de todas** con la fecha (AAAA-MM-DD) y tres apartados: *Decisiones*, *Lo que se
hizo* y *Pendiente*.

---

## 2026-11-20: Fase 6 (factores externos), validación de la pista de ETH y sesión de papel

### Decisiones

- El usuario propuso conectar noticias para anticipar caídas. Se acordó empezar por factores con
  historia gratuita y marca de tiempo precisa: funding e interés abierto de futuros, miedo y
  codicia, y flujo de órdenes. Las noticias quedan para después y solo hacia adelante: un modelo
  de IA que califique noticias viejas ya sabe qué pasó después, y eso contaminaría el backtest.
- **Pares reservados para validación**: SOLUSDT, BNBUSDT y XRPUSDT, solo en 1h. Están en
  `simbolos_validacion` de `config.toml` y no se usan para explorar.
- **Hipótesis antes que resultados**: cada prueba de confirmación (H1, H1b, H2, H2b y H3) se
  escribió en `docs/RESULTADOS.md` con su criterio ANTES de correrla.
- El commit de cada estudio ahora se toma al EMPEZAR a correr. Los estudios #1 a #5 (sin commit)
  se repitieron con el commit `4adb98a` (#6 a #10), dieron lo mismo y se borraron.
- Miedo y codicia se usa con un día de retraso, porque no se sabe a qué hora se publica el valor
  del día.
- El panel pide sus archivos con versión (`?v=`) y `Cache-Control: no-cache`, para que el
  navegador no use un `app.js` viejo después de una actualización.

### Lo que se hizo

- Commit `4adb98a` de las fases 2 a 5.
- **Sesión de papel de ETH en marcha**: `ETHUSDT-1h-momentum`, momentum con ventana=720, como
  proceso independiente sin ventana. El número de proceso está en
  `datos/papel-ETHUSDT-1h-momentum.pid` y el registro en `datos/papel-ETHUSDT-1h-momentum.log`.
  Sigue mientras la PC esté encendida; si se reinicia, hay que relanzarla (ver CLAUDE.md).
- Velas de 1h de SOL, BNB y XRP descargadas.
- Fase 6 (esquema v3):
  - `factores/` (descarga, tabla alineada sin ver el futuro y estudio de eventos);
  - comandos `factores` y `eventos`;
  - estrategias `momentum_apalancamiento` y `momentum_sentimiento`;
  - vista de eventos en el panel.
- Datos de factores descargados:
  - funding de los 6 pares desde 2020;
  - miedo y codicia desde 2018;
  - métricas de futuros de BTC (desde 2020-09), ETH, ZEC y SOL (desde 2021-12). Las de BNB y
    XRP se estaban terminando de bajar al cerrar la sesión.
- Pruebas: **84**, todas pasan, sin red.
- Commit de la fase 6 ("Fase 6: factores externos...").

### Hallazgos (detalle en `docs/RESULTADOS.md`)

- **H1 y H1b rechazadas**: momentum no le gana a las dos referencias en los pares reservados (1 de
  3). La pista de ETH era suerte.
- **H2**: el filtro de apalancamiento ayudó a momentum en 2 de 3 pares explorados, pero no lo
  volvió útil. **H2b rechazada**: en los pares reservados el filtro empeoró los 3.
- **H3 rechazada**: el funding alto solo agrega algo sobre la volatilidad en 1 o 2 de 5 pares.
- Estudio de eventos completo (#18): **la volatilidad reciente es el mejor aviso de caídas, pero
  también de subidas** (alrededor de 10% contra 2%, en los dos sentidos). Ni el interés abierto,
  ni los largos/cortos, ni el flujo anticipan caídas de forma estable. El miedo extremo precede
  caídas, pero no agrega nada sobre la volatilidad.

### Pendiente

- Decidir si se deja corriendo la sesión de papel de ETH (la hipótesis se rechazó, pero da datos
  nuevos de verdad) y si se programa para que arranque sola al encender la PC.
- **Noticias hacia adelante**: un recolector de titulares (RSS) con su hora de publicación. Así
  se acumulan datos limpios y, en unos meses, se pueden estudiar sin contaminación.
- La volatilidad avisa movimientos grandes pero no su dirección. Una idea a probar: reducir el
  tamaño de la posición cuando la volatilidad está alta (gestión de riesgo, no predicción), para
  bajar los drawdowns de 70% a 90%.
- Para hipótesis nuevas hacen falta pares reservados nuevos: SOL, BNB y XRP ya se usaron.

---

## 2026-11-20: Fases 2 a 5 terminadas

### Decisiones

El usuario pidió hacer todas las fases sin plan previo. Claude tomó estas decisiones; están
pendientes de revisión:

- **Costos**: deslizamiento por lado de 0.05% en BTC y ETH y de **0.2% en ZEC**, por su poca
  liquidez. Están en `config.toml`, sección `[costos]`.
- **Reglas del motor**:
  - solo largos (spot), todo o nada, o una fracción fija con `--fraccion`;
  - la señal sale al cierre de una vela y se ejecuta en la apertura de la siguiente vela **con
    operaciones**;
  - al final de cada ventana se vende al cierre, pagando costos;
  - comprar y mantener usa el mismo motor y los mismos costos;
  - "le gana" = mayor rendimiento neto en la misma ventana.
- **Estrategias**: 4, con pocos parámetros y rejillas pequeñas (43 combinaciones en total):
  cruce de medias, ruptura de canal (Donchian), reversión con RSI y momentum.
- **Barrido**: ventanas completa, por año y "desde cada año hasta hoy". Todo es dentro de
  muestra y así se rotula.
- **Walk-forward**:
  - por defecto, 12 meses de entrenamiento y 3 de prueba, con ventana rodante (opción
    `--anclado`);
  - criterios para elegir combinación: `rendimiento` (por defecto) y `calmar`;
  - las pruebas se encadenan y se comparan con comprar y mantener continuo en todo el tramo
    fuera de muestra;
  - se reporta lo que la combinación elegida "prometía" en entrenamiento contra lo que logró en
    prueba, como señal de sobreajuste.
- **Registro**: tablas `estudios` y `corridas` en la misma base. Cada estudio guarda su
  configuración, el número de simulaciones y el commit de git (con `+cambios` si había cambios
  sin commit).
- **Panel**:
  - solo lectura y solo en 127.0.0.1;
  - límite de 150,000 velas por consulta;
  - con muchas operaciones arranca mostrando las últimas 1,500 velas;
  - el capital se ve en escala logarítmica.
- **Papel**: mismo cálculo que el backtest. Si se conecta a mitad de una vela, ejecuta al precio
  del momento y no a la apertura, que ya pasó. Antes de conectarse y en cada reconexión rellena
  por REST lo que falte. El estado queda en SQLite y se retoma por `--nombre`.
- **Esquema v2**: solo agrega tablas; la base existente se migró sola.
- La línea de comandos se separó en `__main__.py` (argumentos), `comandos.py` y `reporte.py`.

### Lo que se hizo

- Paquetes `backtest/`, `validacion/`, `panel/` y `papel/`, más comandos nuevos: `estrategias`,
  `backtest`, `barrido`, `walk-forward`, `estudios`, `panel` y `papel`.
- Hay **71 pruebas**, todas pasan, sin red. Entre ellas:
  - costos calculados a mano;
  - ninguna estrategia ve el futuro;
  - la operación en papel reproduce exactamente las operaciones del backtest;
  - pruebas del panel y del walk-forward.
- Todo el código pasa el análisis de sintaxis de Python 3.11.
- Primeros estudios, guardados en la base (#1 a #5; detalle en `docs/RESULTADOS.md`):
  - un barrido de 3,612 simulaciones;
  - un walk-forward de 6,768 simulaciones;
  - 3 walk-forward de robustez en 1h.
- El panel se probó con la base real y con capturas de Edge en modo sin ventana: Backtest,
  Estudios y Papel.
- El papel se probó en vivo 3 minutos (BTCUSDT 1m) contra el websocket de Binance: compró,
  vendió y volvió a comprar según las reglas. Después se borraron esa sesión de prueba y las
  1,102 velas de 1m que bajó.

### Hallazgos

- Con costos reales, el resultado coincide con el ensayo original. **En 5m todo se ahoga en
  comisiones** (de −97% a −100% fuera de muestra). En 1h casi nada le gana a las dos referencias.
- Fuera de muestra, 2 de 24 configuraciones le ganaron a las dos:
  - cruce de medias en ZEC 1h no aguantó las pruebas de robustez;
  - **momentum en ETH 1h sí aguantó en 3 de 4**, casi siempre con ventana=720, pero con caídas
    de 50% a 74%. Es una pista, no evidencia: salió de mirar 24 configuraciones.

### Pendiente

- **Commit de las fases 2 a 5** cuando el usuario lo indique. Después, repetir los estudios para
  que queden atados al commit; los actuales dicen `4fbd9c3+cambios`.
- Revisar con el usuario las decisiones de arriba, sobre todo los deslizamientos y el criterio
  de "le gana".
- Validar momentum en ETH 1h con datos que nadie ha mirado:
  - otros pares (SOL, BNB, XRP: hay que agregarlos a `config.toml` y descargarlos);
  - o una sesión de papel larga (`papel --simbolo ETHUSDT --intervalo 1h --estrategia momentum
    --param ventana=720`).
- Ideas abiertas en `docs/RESULTADOS.md`:
  - sensibilidad a los costos;
  - walk-forward que se quede fuera cuando nada gana en entrenamiento.
- Para correr 24 horas (papel o descarga periódica) hace falta la PC encendida sin suspenderse,
  o un servidor.

---

## 2026-11-20: Fase 1 terminada, recolector de velas

### Decisiones

- El usuario aprobó el plan de la fase 1 tal como estaba: API REST directa de Binance (sin
  ccxt), columnas en español, historial desde 2020-01-01 00:00 UTC.
- El usuario aprobó los principios 6 (sin información del futuro) y 7 (reproducibilidad).
- Al cruzar 5m contra 1h, las velas sin operaciones se ignoran al juntar, porque así arma
  Binance sus velas (ver *Hallazgos*).

### Lo que se hizo

- Entorno virtual `.venv/` con Python 3.14.5; instalado el proyecto en modo editable con
  `requests` y `pytest`. El código pasa el análisis de sintaxis de Python 3.11.
- Código: `config.toml`, `pyproject.toml` y el paquete `tradinglab/` con `config.py`, `db.py`,
  `tiempo.py` (agregado al plan), `__main__.py` y `recolector/` con `binance.py`,
  `descarga.py` y `verificacion.py`. Hay 32 pruebas, todas pasan, sin red.
- Primera descarga real: 724,063 velas de 5m y 60,345 de 1h por par (2,353,224 en total), en
  2,364 peticiones y 13.9 minutos, sin errores. La base `datos/tradinglab.sqlite` pesa 253 MB.
- La segunda corrida solo agregó las velas que cerraron entre tanto (de 1 a 3 por serie): no
  duplica y reanuda bien.
- `verificar`: 0 velas inválidas en las 6 series; el cruce 5m contra 1h coincide en las
  60,331 horas comparables de cada par (14 horas incompletas por huecos no se comparan).
- La ventana de VS Code se pintó de morado (ver la entrada del arranque).
- Primer commit, `5b471e1`, con el arranque y la fase 1. El cambio a esta bitácora que lo
  registra va en un segundo commit.

### Hallazgos

- **Huecos**: 15, idénticos en BTC, ETH y ZEC (mantenimientos de todo Binance), 466 velas de 5m
  en total. Los más grandes: 2020-02-19 (70 velas de 5m), 2021-04-25 (56), 2021-08-13 (54),
  2020-12-21 (50) y 2020-06-28 (42). El último es del 2023-03-24 (16 velas). Desde entonces no
  hay huecos.
- **Velas sin operaciones**: Binance llena una vela de 5m sin operaciones con el cierre
  anterior, pero la vela de 1h solo usa precios donde hubo operaciones. Eso causó 51
  diferencias aparentes en ZEC en la primera verificación; no eran errores de datos. ZEC tiene
  2,951 velas de 5m sin operaciones (0.4%); BTC y ETH, 31 cada uno. Es una señal de la poca
  liquidez de ZEC.
- Precio al cierre de la descarga (2026-11-20 17:35 UTC): BTC unos 59,300 USDT, ETH unos
  1,630, ZEC unos 752.

### Pendiente

- Fase 2, motor de backtest:
  - deslizamiento por defecto, probablemente mayor para ZEC por su poca liquidez;
  - cómo tratar huecos y velas sin operaciones (no llenar órdenes donde no hubo precio real).
- Más adelante: correr `descargar` de forma periódica (Programador de tareas de Windows o un
  servidor) para mantener la base al día.

---

## 2026-11-20: Arranque del proyecto

### Contexto

La idea sale de un ensayo publicado en Facebook: un bot autónomo de trading (Python 3.11 en
Debian 12, panel web, SQLite con datos desde 2020, corriendo 24 horas) que estudió BTC, ETH y ZEC
con unas 800 simulaciones y 4 variantes de estrategia, de conservadora a "kamikaze", y concluyó
que nada le ganó a no operar. Las instrucciones originales del usuario están en
`prompt_inicio.md`, en la raíz.

### Decisiones

- TradingLab es un **laboratorio de investigación, no una máquina de dinero**. No se opera con
  dinero real; conectarlo a dinero real algún día es decisión del usuario y queda fuera del
  alcance del proyecto.
- Principios del usuario: costos reales (0.1% por lado más deslizamiento), comparación contra no
  operar y contra comprar y mantener, validación fuera de muestra (walk-forward), cuidado con el
  sobreajuste, y métricas mínimas (rendimiento neto, drawdown máximo, número de operaciones,
  comisiones pagadas y porcentaje de ganadoras).
- Cinco fases: recolector, motor de backtest, validación y corridas masivas, panel web,
  operación en papel.
- Python mínimo 3.11 (un servidor Debian 12 trae esa versión); localmente hay Python 3.14.5.
  Entorno virtual en `.venv/`.
- Español en documentación, comentarios, mensajes y nombres de código (sin acentos ni ñ).
- Todos los instantes en UTC, en milisegundos desde epoch.
- Esta bitácora va de la entrada más reciente a la más antigua.

### Lo que se hizo

- Se revisó la API pública de Binance (sin llaves): **los tres pares están disponibles** y en
  estado TRADING. BTCUSDT y ETHUSDT tienen velas desde 2017-08-17 y ZECUSDT desde 2019-03-21,
  así que los tres cubren desde 2020. Las velas traen 12 campos. Límite: 6000 de peso por
  minuto por IP; cada petición de velas pesa 2.
- Se crearon `CLAUDE.md`, `docs/HISTORIAL.md`, `docs/PLAN_FASE1.md` y `.gitignore`.
- Se inicializó git (rama `main`). Todavía no hay commits.
- La ventana de VS Code de este proyecto se pintó de morado (`.vscode/settings.json`), igual
  que TMS en rosa y Digbit en azul. `.vscode/` quedó en `.gitignore` por ser preferencia local.
- Se propuso el plan de la fase 1 en `docs/PLAN_FASE1.md`: API REST directa de Binance (sin
  ccxt, para conservar número de operaciones y volumen taker), tabla `velas` con llave primaria
  `(simbolo, intervalo, ts)`, descarga incremental por lotes de 1000 con commit por lote, y los
  comandos `descargar` y `verificar`.

### Pendiente

- **Visto bueno del usuario al plan de la fase 1**, incluidas las decisiones abiertas de la
  sección 7 del plan (API directa o ccxt, nombres de columnas, fecha de inicio).
- Confirmar los principios 6 (sin información del futuro) y 7 (reproducibilidad) que propuso
  Claude en `CLAUDE.md`.
- Hacer el primer commit cuando el usuario lo indique.
- Fase 2: decidir el deslizamiento por defecto (quizá distinto por par, porque ZEC es menos
  líquido que BTC y ETH).
