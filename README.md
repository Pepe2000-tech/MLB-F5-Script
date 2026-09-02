# MLB Betting Hub V7.6.4 Alpha — Paper Parlays completos

V7.6.4 corrige la estructura de Paper Betting para parlays.

## Cambio principal

Un parlay guardado desde la pestaña **Parlays** ahora se registra como **una sola Paper Bet completa**, no como varias apuestas individuales.

El registro padre conserva internamente todas sus piernas para poder resolverlas con MLB, pero el monto apostado, resultado, ROI, ganancia/pérdida y conteo de apuestas se contabilizan una sola vez.

### Ejemplo

Un parlay de 4 selecciones y $50 MXN se guarda como:

- 1 Paper Bet
- Momio combinado del ticket
- $50 MXN apostados una sola vez
- Retorno potencial del parlay completo
- 4 piernas embebidas para liquidación

En Paper Bets puede expandirse con **Ver N selecciones** para revisar cada pierna y su estado.

## Liquidación

- Si cualquier pierna pierde, el parlay completo queda LOST.
- Si todavía faltan partidos y ninguna pierna perdió, queda PENDING.
- Los PUSH no cuentan como derrota.
- Si todas las piernas restantes ganan y no hay pendientes, el parlay queda WON.
- Si todas fueran PUSH, queda PUSH.

## Rendimiento

Los parlays nuevos cuentan como una sola apuesta en Rendimiento, por lo que no inflan artificialmente número de apuestas, stake, ROI ni hit rate.

## CSV

Las piernas y sus resultados se exportan como JSON dentro del CSV (`legs_json` y `leg_results_json`) y se restauran al importar el archivo.

## Se mantiene de V7.6.3

- Multi-Parlays independientes de Express.
- 1–5 parlays por búsqueda.
- 2–8 juegos por parlay.
- Perfiles Menor riesgo / Equilibrado / Mayor ganancia.
- Mercados seleccionables.
- Edición de líneas y momios con recálculo total.
- Paper Bets individuales desde Express.
- Eliminación individual de Paper Bets.
- Statcast/Savant, Bet Quality, calibración y Gate de calidad.
- Exclusión de partidos iniciados/Final en nuevas búsquedas.

## Persistencia

El respaldo local sigue funcionando durante la misma instancia de Streamlit. Para persistencia tras reinicios/redeploys, configura Supabase con los Secrets ya utilizados en versiones anteriores.
