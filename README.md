# MLB Betting Hub V6.5 — Pre-mercado

Esta versión está pensada para dejar de modificar el modelo constantemente y comenzar una prueba seria.

## Nuevo
- Horarios CDMX (conservado de V6.1)
- Semáforo antes de cerrar una predicción:
  - 🟢 LISTO PARA PAPER TEST
  - 🟡 ESPERAR / REVISAR
  - 🔴 NO CERRAR ANÁLISIS
- Recomendación de cuándo volver a actualizar según tiempo al juego.
- `Qué cambió desde tu última actualización`:
  - abridores
  - número de jugadores del lineup
  - clima
  - bullpen
  - proyección F5 / Full Game
- Carga de bullpen expresada como BAJA / MEDIA / ALTA.
- Paper Betting:
  - congela la predicción exacta
  - momio
  - probabilidad central / conservadora
  - confianza
  - acuerdo
  - lineups confirmados o no
  - calidad de datos
  - versión del modelo
- Resolución automática desde MLB para:
  - F5 totals
  - F5 ML
  - Full Game totals
  - Full Game ML
  - Pitcher Ks
  - Hits
  - Total Bases
  - Home Runs
- Exportar e importar Paper Betting CSV.
- Dashboard:
  - acierto
  - ROI paper
  - unidades
  - Brier Score
  - Log Loss
  - calibración por rangos
  - rendimiento por categoría

## Regla para probar V6.5
No modificar el algoritmo después de cada pérdida.
Congelar un bloque de predicciones y revisar el modelo cuando exista una muestra razonable.

## Limitaciones
- Streamlit Community Cloud no garantiza persistencia local: exporta el CSV.
- Statcast avanzado todavía no está integrado.
- Full Game sigue dependiendo parcialmente de proxies de bullpen.
