# MLB Betting Hub V4.1

Objetivo:
1. Escoger fecha y partido.
2. La app analiza automáticamente F5, juego completo y player props.
3. Sin conocer momios, genera hasta 5 opciones que conviene buscar en Draftea.
4. En la segunda pantalla el usuario selecciona cuáles encontró y captura el momio.
5. La app evalúa si el precio realmente vale la pena.

## Pantalla 1 — Qué buscar
No pide momios.

Analiza automáticamente:
- abridores
- ERA, WHIP, K/9, BB/9, HR/9
- ofensiva temporada y últimos 15
- parque
- clima
- lineups oficiales cuando MLB los publica
- OPS y posición de los 9 bateadores
- F5
- juego completo con bullpen/staff proxy
- props de pitcher y bateadores

Entrega:
- Top 5
- probabilidad del modelo
- cuota justa
- cuota mínima objetivo
- estado confirmado/provisional
- explicación breve

## Pantalla 2 — Evaluar momios
El usuario selecciona solamente entre el Top automático y captura las cuotas reales de Draftea.

La app devuelve:
- probabilidad
- cuota justa
- cuota mínima objetivo
- EV
- APOSTAR / LEAN / PASS
- mejor opción entre las seleccionadas

## Importante
El ranking sin momio NO significa que todas sean apuestas.
La Pantalla 1 dice qué mercados buscar.
La Pantalla 2 decide si el precio es suficientemente bueno.

Full Game y Player Props siguen siendo módulos experimentales.
