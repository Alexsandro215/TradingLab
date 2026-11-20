# Resultados de la investigación

Hallazgos de los estudios guardados en la base (`python -m tradinglab estudios <id>` los
muestra completos; el panel también). Lo más reciente va arriba.

---

## 2026-11-20: Fase 6. Estudio de eventos completo (estudio #18)

¿Algún factor avisa ANTES de las caídas fuertes? Se probaron BTC, ETH y ZEC en 1h. "Caída" es el
5% peor de los rendimientos a 24 h, unas 140 caídas independientes en entrenamiento
(2020-2023) y entre 58 y 111 en prueba (2024 a hoy).

| Factor | BTC | ETH | ZEC | Lectura |
|---|---|---|---|---|
| Volatilidad de 24 h (ref.) | 1.9x → 2.4x | 2.1x → 2.0x | 2.1x → 2.1x | **el mejor aviso, estable en todo** |
| Rendimiento de 24 h, quintil más bajo (ref.) | 1.6x → 1.7x | 1.7x → 2.1x | 1.4x → 1.3x | después de una baja vienen más bajas |
| Funding de 3 días | **agrega** | se sostiene, no agrega | **agrega** (quintil 4) | ver H3: no se generaliza |
| Funding del momento | no | no | agrega | inestable |
| Cambio del interés abierto en 24 h | no | no | no | **no avisa** |
| Largos/cortos de cuentas grandes | no | no | se sostiene, no agrega | no avisa |
| Flujo agresivo en futuros y en spot | no | no | no | no avisa |
| Miedo y codicia (miedo extremo) | 1.8x → 1.25x | 2.0x → 1.2x | 1.8x → 1.3x | el miedo precede caídas, pero es la misma volatilidad |

"x" = probabilidad de caída en el quintil más riesgoso entre la tasa base, en entrenamiento →
prueba. "Agrega" = también le gana a lo que predice la volatilidad sola (≥ 1.2x en los dos
periodos).

- Contando este estudio y el #16, se evaluaron **63 combinaciones de factor y par**. Con tantas
  pruebas, unos cuantos "sí" salen por azar, y eso es lo que se ve: aparecen en pares sueltos y
  no se repiten.
- **La idea de que el apalancamiento (interés abierto creciendo) anticipa las caídas no se
  confirma** con estos datos y reglas.
- Lo único consistente sale del propio precio: tras volatilidad alta y bajas recientes vienen
  más caídas. Pero eso no da dirección. Se comprobó en todo el periodo: en el quintil de
  volatilidad más alto, la probabilidad de una **caída** fuerte a 24 h es de 9.6% a 10.4%, y la
  de una **subida** fuerte (el 5% mejor), de 9.6% a 12.1%, en los tres pares. En el quintil más
  bajo, las dos andan en 2%. La volatilidad anuncia movimientos grandes, no su dirección.

---

## 2026-11-20: Fase 6. Hipótesis H3, registrada después de ver SOLO BTC

En el estudio de eventos de BTCUSDT 1h (horizonte de 24 h, corte 2024-01-01), el único factor que
anticipa caídas y además agrega algo más allá de la volatilidad es **`funding_3d` en su quintil
más alto** (los cortes son los del entrenamiento):
- P(caída) de 1.64x la base en entrenamiento y de 2.51x en prueba;
- frente a lo que predice la volatilidad sola: 1.31x y 1.67x.

Ningún otro factor (interés abierto, largos y cortos, flujo, miedo y codicia) pasó las dos
pruebas en BTC.

**H3.** En el mismo estudio, `funding_3d` en su quintil más alto "se sostiene" (≥ 1.25x la base en
entrenamiento y en prueba) y "agrega sobre la volatilidad" (≥ 1.20x en los dos periodos).
- Pares: ETHUSDT y ZECUSDT (no se han mirado con este factor) y los reservados SOLUSDT,
  BNBUSDT y XRPUSDT.
- **Se acepta si se cumple en al menos 3 de los 5 pares.**

### Resultado de H3 (estudio #16): RECHAZADA

| Par | Quintil con más caídas (entren.) | P(caída) entren. → prueba | Frente a la volatilidad, entren. → prueba | ¿Cumple H3? |
|---|---|---|---|---|
| ETHUSDT | 5 | 1.50x → 1.27x | 1.14x → 1.10x | no: no agrega sobre la volatilidad |
| ZECUSDT | **4** | 1.49x → 1.57x | 1.23x → 1.34x | no: el más riesgoso es el 4, no el más alto |
| SOLUSDT | **1** (el más bajo) | 1.29x → 1.35x | 1.08x → 1.24x | no |
| BNBUSDT | 5 | 1.68x → 1.98x | 1.27x → 0.96x | no: en prueba no agrega |
| XRPUSDT | 5 | 2.01x → 1.95x | 1.31x → 1.36x | **sí** |

- Cumple en 1 de 5 pares (2 si se perdona el quintil de ZEC). Pedía 3. **Se rechaza.**
- Lectura: el funding alto **sí** precede más caídas en casi todos los pares, pero sobre todo
  porque **coincide con volatilidad alta**. Lo que avisa, casi siempre ya lo avisaba la
  volatilidad. Lo de BTC fue, en buena parte, suerte del par.

### Resultado de H2b (estudio #17): RECHAZADA

| Par | Momentum sin filtro (#11) | Con filtro de apalancamiento (#17) |
|---|---|---|
| SOLUSDT | +730%, dd −75% | +54%, dd −76%: peor |
| BNBUSDT | +230%, dd −79% | −14%, dd −81%: peor |
| XRPUSDT | −44%, dd −88% | −78%, dd −90%: peor |

- El filtro empeora a momentum en los 3 pares reservados (pedía mejorar en 2 de 3).
- Nota justa: la rejilla del filtrado solo tiene ventanas de 168 y 720 y la de momentum tiene 6,
  así que parte de la diferencia puede ser la rejilla. Aun así, ningún par mejora.

### Conclusión de la fase 6 (hasta aquí)

Ni el apalancamiento ni el sentimiento sirven para esquivar caídas de forma confiable con estas
reglas. Ayudan en algunos pares y en otros no, que es lo que se espera del azar cuando se
prueban varias ideas. **La volatilidad reciente es el mejor aviso de caídas**, y no es
direccional: también avisa subidas fuertes. La conclusión del ensayo original sigue en pie.

---

## 2026-11-20: Fase 6. Hipótesis H2, registrada antes de ver el estudio de eventos

Los dos filtros se eligieron por lo que se sabe del mercado cripto, no por los datos. Las caídas
fuertes suelen venir de liquidaciones en cadena cuando hay demasiados largos apalancados
(funding alto), o después de periodos de euforia.

- `momentum_apalancamiento`: momentum, pero fuera cuando el funding promedio de 3 días pasa de un
  umbral. Rejilla: ventana 168 o 720; umbral 0.02% o 0.04% por cobro.
- `momentum_sentimiento`: momentum, pero fuera cuando el índice de miedo y codicia pasa de un
  umbral. Rejilla: ventana 168 o 720; umbral 75 u 85.

**H2.** Walk-forward de 12 meses de entrenamiento y 3 de prueba, criterio `rendimiento`, en
BTCUSDT, ETHUSDT y ZECUSDT 1h:
- **"El filtro ayuda"** si, en al menos 2 de los 3 pares, la versión filtrada tiene mayor
  rendimiento Y menor drawdown que momentum sin filtro en el estudio #9.
- **"Estrategia útil"** solo si además le gana a no operar y a comprar y mantener en al menos
  2 de los 3 pares.
- Aviso: BTC, ETH y ZEC ya se exploraron mucho. Si algo pasa, hay que confirmarlo en pares
  reservados nuevos.

### Resultado de H2 (estudio #15)

| Par | Momentum sin filtro (#9) | Con filtro de apalancamiento | Con filtro de sentimiento | C&M |
|---|---|---|---|---|
| BTCUSDT 1h | +70%, dd −63% | +20%, dd −69%: peor | +43%, dd −55%: mixto | +105% |
| ETHUSDT 1h | +253%, dd −60% | **+347%, dd −51%: mejor** | +230%, dd −58%: mixto | +121% |
| ZECUSDT 1h | +87%, dd −98% | **+675%, dd −94%: mejor** | **+229%, dd −95%: mejor** | +1,077% |

- **Filtro de apalancamiento: "ayuda" en 2 de 3 pares**, así que cumple. Como "estrategia útil"
  **no**: le gana a las dos referencias solo en ETH (1 de 3).
- **Filtro de sentimiento: no ayuda** (1 de 3).
- Siguiente paso, registrado aquí antes de correrlo, **H2b**: el filtro de apalancamiento
  "ayuda" (más rendimiento y menos drawdown que momentum sin filtro del estudio #11, con el
  mismo walk-forward) en al menos 2 de 3 pares reservados: SOLUSDT, BNBUSDT y XRPUSDT. En esos
  pares ya se vio momentum sin filtro, pero no el efecto del filtro.

---

## 2026-11-20: Hipótesis registrada ANTES de mirar los pares de validación

Se escribió antes de correr cualquier estudio con SOL, BNB o XRP. Ninguno de los tres se había
usado; solo se descargaron sus velas de 1h.

**H1. Momentum en 1h le gana a no operar y a comprar y mantener fuera de muestra.**
- Procedimiento fijo, el mismo del estudio #9: estrategia `momentum` con su rejilla de siempre,
  walk-forward de 12 meses de entrenamiento y 3 de prueba, criterio `rendimiento`, costos de
  `config.toml` (deslizamiento 0.05% para estos pares).
- Pares: SOLUSDT, BNBUSDT y XRPUSDT, intervalo 1h.
- **Se acepta si le gana a las dos referencias en al menos 2 de los 3 pares.** Si no, se descarta
  la pista de ETH como suerte.

**H1b, complementaria.** `momentum` con `ventana=720` fija, sin elegir parámetros, en todo el
historial de cada par. Mismo criterio: le gana a las dos referencias en al menos 2 de 3. Como
720 salió de mirar ETH, esta prueba solo es válida en los pares nuevos.

### Resultado: H1 y H1b RECHAZADAS (estudios #11 a #14)

Código del commit `4adb98a`. Los estudios dicen `+cambios` porque ya había cambios de la fase 6
sin commit en la configuración, el esquema y los módulos nuevos; el código del walk-forward y del
backtest era el mismo.

| Par | H1: walk-forward fuera de muestra (#11) | C&M en ese tramo | H1b: ventana=720 fija (#12 a #14) | C&M |
|---|---|---|---|---|
| SOLUSDT | **+730%** (dd −75%) | +64% | **+8,125%** (dd −71%) | +2,324% |
| BNBUSDT | +230% (dd −79%) | +1,349% | +711% (dd −70%) | +3,848% |
| XRPUSDT | −44% (dd −88%) | +312% | +53% (dd −84%) | +369% |

- Las dos le ganan a las dos referencias solo en **1 de 3** pares, y el criterio pedía 2. **La
  pista de momentum en ETH se descarta como suerte.**
- Lo que sí se repite: momentum casi siempre le gana a **no operar** (5 de 6), pero en un mercado
  que en el periodo subió mucho no le gana a **comprar y mantener**, y sus caídas siguen siendo
  de 70% a 88%.
- SOL es el caso que brilla, pero es uno de tres: justo lo que pasaría por azar.
- SOL, BNB y XRP ya se miraron. Para una próxima hipótesis hacen falta pares reservados nuevos.

---

## 2026-11-20: Primera ronda (estudios #6 a #10, commit `4adb98a`)

**Condiciones comunes:** datos de Binance spot desde 2020-01-01 hasta 2026-11-20; capital de
1,000 USDT; comisión de 0.1% por lado; deslizamiento de 0.05% por lado en BTC y ETH y de 0.2% en
ZEC. Las estrategias solo compran (spot); entran con todo el capital y salen con todo. Son 4
estrategias con 43 combinaciones de parámetros (ver `python -m tradinglab estrategias`).

> Primero se corrieron con código sin commit (estudios #1 a #5). Se repitieron con el commit
> `4adb98a` y dieron lo mismo, salvo por una vela más de ETH 1h que entró entre una corrida y
> otra. Los #1 a #5 se borraron.

### Barrido (estudio #10, todo dentro de muestra)

Se corrieron 3,612 simulaciones: 43 combinaciones × 3 pares × 2 intervalos × 14 ventanas
(completa, cada año y "desde cada año hasta hoy").

- Le ganan a no operar: 23.5%. A comprar y mantener: 13.5%. **A las dos: 4.5%** (164 de 3,612).
- La mediana de rendimiento es negativa en las 4 estrategias. Va de −39% en RSI a −99% en
  momentum, que en 5m se ahoga en comisiones.
- En la ventana completa, comprar y mantener gana: +725% en BTC, +2,636% en ZEC.
- Solo en años bajistas (2022, por ejemplo) aparecen combinaciones que superan a las dos
  referencias. Ese "mejor" sale de entre 43 intentos, así que está inflado por suerte.

### Walk-forward (estudio #9): 12 meses de entrenamiento y 3 de prueba, criterio rendimiento

El periodo fuera de muestra va de 2021-01-01 a 2026-11-20. Son 24 configuraciones (3 pares ×
2 intervalos × 4 estrategias) y 6,768 simulaciones.

- **En 5m, todo pierde** salvo RSI en ZEC. Cruce de medias, ruptura y momentum terminan entre
  −97% y −100% por costos: de 1,500 a 5,700 operaciones.
- Le ganan a no operar 6 de 24 configuraciones. A comprar y mantener, 2. **A las dos, 2:**
  - momentum en ETHUSDT 1h: +253% contra +121% de comprar y mantener, con drawdown de −60%;
  - cruce de medias en ZECUSDT 1h: +1,176% contra +1,077%, con drawdown de −92%.
- Sobreajuste visible en casi todo: en 1h, la combinación elegida "prometía" en entrenamiento
  entre +3% y +7% mensual, y en prueba logró casi siempre entre −2% y +2% mensual.

### Robustez de esos 2 casos (estudios #6, #7 y #8, solo 1h)

| Configuración del walk-forward | momentum ETH 1h | cruce de medias ZEC 1h |
|---|---|---|
| 12 m / 3 m, rendimiento (#9) | le gana a las dos | le gana a las dos |
| 6 m / 3 m, rendimiento (#6) | +271% contra +627%: no | +230% contra +1,364%: no |
| 24 m / 6 m, rendimiento (#7) | +95% contra −55%: le gana a las dos | +66% contra +414%: no |
| 12 m / 3 m, criterio calmar (#8) | +171% contra +123%: le gana a las dos | +612% contra +1,077%: no |

Cada configuración tiene su propio tramo fuera de muestra (empieza al terminar el primer
entrenamiento), por eso el rendimiento de comprar y mantener cambia de una fila a otra.

### Conclusión provisional

1. Coincide con el ensayo original: **con costos reales, casi nada le gana a no operar y a
   comprar y mantener a la vez**, y en 5m los costos arrasan con todo.
2. El cruce de medias en ZEC era suerte: no aguanta otras configuraciones de walk-forward.
3. **Momentum en ETH 1h es la única pista que se sostiene** en 3 de 4 configuraciones. Pero:
   - se eligió después de mirar 24 configuraciones, así que también puede ser suerte (sobreajuste
     al nivel del investigador);
   - sus caídas son del 50% al 74%;
   - para tomarla en serio hay que probarla en datos que nadie ha mirado: otros pares, o los
     meses que vengan, en papel.

### Ideas para la siguiente ronda

- Probar momentum en 1h con pares que no se han usado (por ejemplo SOL, BNB o XRP) como
  validación independiente.
- Operación en papel de momentum en ETHUSDT 1h para acumular resultados realmente nuevos.
- Una variante de walk-forward que se quede fuera (no operar) cuando nada gana en
  entrenamiento.
- Medir la sensibilidad a los costos: con qué comisión desaparece la ventaja de momentum en ETH.
