Hola. Vamos a empezar un proyecto nuevo en esta carpeta (A:\TradingLab). Antes de escribir código, quiero que armes el historial de contexto del proyecto.

## De dónde sale la idea
Vi en Facebook el ensayo de un bot autónomo de trading: Python 3.11 en Debian 12, con panel web en el navegador. Recolecta operaciones y volúmenes desde 2020 en SQLite y funciona 24 horas. Sus sujetos de estudio son BTC, ETH y ZEC. En 3 días corrió unas 800 simulaciones por línea de comandos, con ventanas desde 2020 hasta hoy y ventanas intermedias, y 4 variantes de estrategia que van de conservadora a "kamikaze". Su conclusión: nada le ganó a NO OPERAR.

Queremos hacer algo parecido, pero como laboratorio de investigación, no como máquina de dinero. No se opera con dinero real. Conectarlo algún día a dinero real sería decisión mía y queda fuera del alcance de este proyecto.

## Principios
- Toda simulación cobra la comisión real (unos 0.1% por lado en Binance) y un deslizamiento de precio.
- Toda estrategia se compara siempre contra dos referencias: no operar, y comprar y mantener.
- Validación fuera de muestra (walk-forward): se optimiza en un periodo y se prueba en otro que la estrategia no vio. Cuidado con el sobreajuste al probar muchas combinaciones.
- Métricas mínimas: rendimiento neto, drawdown máximo, número de operaciones, comisiones pagadas y porcentaje de operaciones ganadoras.

## Fases
1. Recolector: Python con ccxt o la API pública de Binance (sin llaves) hacia SQLite. Velas OHLCV de BTC/USDT, ETH/USDT y ZEC/USDT desde 2020, en 5m y 1h para empezar. Descarga incremental (reanuda donde se quedó) y sin duplicados. Si algún par no está disponible, avísame.
2. Motor de backtest con costos reales y las dos referencias.
3. Validación fuera de muestra y corridas masivas por línea de comandos.
4. Panel web: FastAPI con TradingView Lightweight Charts, con las operaciones marcadas sobre las velas, el capital y el drawdown.
5. Operación en papel con datos en vivo por websocket, sin dinero real.

Entorno: Windows 11, Python 3.11 o más nuevo, en un entorno virtual (venv) dentro del proyecto. Más adelante quizá un servidor para correrlo 24 horas.

## Lo que quiero que hagas ahora
1. Crea CLAUDE.md en la raíz con: qué es el proyecto, los principios, las fases, el stack y las convenciones. Todo en español.
2. Crea docs/HISTORIAL.md: una bitácora con fecha donde se anotan las decisiones, lo que se hizo y lo que queda pendiente. Agrega la primera entrada con la fecha de hoy describiendo este arranque. En CLAUDE.md deja la regla de leer el historial al empezar cada sesión y de agregar una entrada nueva al terminarla.
3. Inicializa git con un .gitignore para Python que ignore el venv, la base SQLite y los datos descargados.
4. Todavía no escribas el recolector. Propónme el plan de la fase 1 (estructura de carpetas, esquema de la tabla de velas y cómo vas a descargar el historial) y espera mi visto bueno.
