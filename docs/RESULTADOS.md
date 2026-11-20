# Resultados de la investigación

Hallazgos de los estudios guardados en la base (`python -m tradinglab estudios <id>` los
muestra completos; el panel también). Lo más reciente va arriba.

---

## 2026-11-20: Primera ronda (estudios #1 a #5)

**Condiciones comunes:** datos de Binance spot desde 2020-01-01 hasta 2026-11-20; capital de
1,000 USDT; comisión de 0.1% por lado; deslizamiento de 0.05% por lado en BTC y ETH y de 0.2% en
ZEC. Las estrategias solo compran (spot); entran con todo el capital y salen con todo. Son 4
estrategias con 43 combinaciones de parámetros (ver `python -m tradinglab estrategias`).

> Los estudios se corrieron con código sin commit (`4fbd9c3+cambios`). Para que queden atados a
> una versión exacta del código hay que repetirlos después del commit de las fases 2 a 5.

### Barrido (estudio #1, todo dentro de muestra)

Se corrieron 3,612 simulaciones: 43 combinaciones × 3 pares × 2 intervalos × 14 ventanas
(completa, cada año y "desde cada año hasta hoy").

- Le ganan a no operar: 23.5%. A comprar y mantener: 13.5%. **A las dos: 4.5%.**
- La mediana de rendimiento es negativa en las 4 estrategias. Va de −39% en RSI a −99% en
  momentum, que en 5m se ahoga en comisiones.
- En la ventana completa, comprar y mantener gana: +725% en BTC, +2,636% en ZEC.
- Solo en años bajistas (2022, por ejemplo) aparecen combinaciones que superan a las dos
  referencias. Ese "mejor" sale de entre 43 intentos, así que está inflado por suerte.

### Walk-forward (estudio #2): 12 meses de entrenamiento y 3 de prueba, criterio rendimiento

El periodo fuera de muestra va de 2021-01-01 a 2026-11-20. Son 24 configuraciones (3 pares ×
2 intervalos × 4 estrategias) y 6,768 simulaciones.

- **En 5m, todo pierde** salvo RSI en ZEC. Cruce de medias, ruptura y momentum terminan entre
  −97% y −100% por costos: de 1,500 a 5,700 operaciones.
- Le ganan a no operar 6 de 24 configuraciones. A comprar y mantener, 2. **A las dos, 2:**
  - momentum en ETHUSDT 1h: +253% contra +123% de comprar y mantener, con drawdown de −60%;
  - cruce de medias en ZECUSDT 1h: +1,176% contra +1,077%, con drawdown de −92%.
- Sobreajuste visible en casi todo: en 1h, la combinación elegida "prometía" en entrenamiento
  entre +3% y +7% mensual, y en prueba logró casi siempre entre −2% y +2% mensual.

### Robustez de esos 2 casos (estudios #3, #4 y #5, solo 1h)

| Configuración del walk-forward | momentum ETH 1h | cruce de medias ZEC 1h |
|---|---|---|
| 12 m / 3 m, rendimiento (#2) | le gana a las dos | le gana a las dos |
| 6 m / 3 m, rendimiento (#3) | +271% contra +627%: no | +230% contra +1,364%: no |
| 24 m / 6 m, rendimiento (#4) | +95% contra −55%: le gana a las dos | +66% contra +414%: no |
| 12 m / 3 m, criterio calmar (#5) | +171% contra +123%: le gana a las dos | +612% contra +1,077%: no |

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
