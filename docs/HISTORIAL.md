# Historial del proyecto

Bitácora de TradingLab. Al empezar cada sesión se lee este archivo; al terminarla se agrega una
entrada **arriba de todas** con la fecha (AAAA-MM-DD) y tres apartados: *Decisiones*, *Lo que se
hizo* y *Pendiente*.

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
