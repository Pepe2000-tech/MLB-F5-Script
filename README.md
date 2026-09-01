# MLB Betting Hub V6.5.4 — FINAL DE PRUEBAS

Esta es una actualización **bugfix** de V6.5.3. El motor estadístico permanece congelado.

## Cambio sobre V6.5.3
- No cambia probabilidades, pesos, filtros, simulación Monte Carlo ni lógica de confianza.
- Corrige las marcas de tiempo visibles para usar explícitamente la zona horaria de CDMX: `America/Mexico_City`.
- `Última consulta` ahora muestra la hora real de CDMX y ya no la hora UTC del servidor de Streamlit.
- El historial de análisis también guarda la hora en CDMX.
- La congelación de Paper Bets sigue guardando hora CDMX e ISO con zona horaria.
- Se actualiza la trazabilidad de nuevas Paper Bets a `model_version = V6.5.4`.

## Regla de prueba
Esta versión solo corrige el bug de zona horaria. No se modificó el algoritmo de predicción.
