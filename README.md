# MLB Betting Hub V7.6 Alpha — Pre-Bet Hardening

V7.6 toma V7.5 como base y añade una capa de control de calidad antes de etiquetar una selección como **APOSTAR**.

## Qué cambia

- Gate final de calidad por mercado.
- Exige lineups confirmados para un verde estricto.
- Penaliza calidad de datos baja e intervalos de incertidumbre amplios.
- Usa confiabilidad del mercado y Bet Quality como requisitos, no solo como información visual.
- Hits, Total Bases y Home Run requieren cobertura Statcast suficiente para recibir verde estricto.
- Home Run tiene reglas más duras por su varianza natural.
- Pitcher Ks requiere una confianza mínima más alta.
- Si se activan momios, una selección sin referencia compatible o con PASS no puede ser verde.
- Express sigue excluyendo juegos Live/Final y vuelve a consultar lineups en cada búsqueda.
- Los picks que no pasan el gate siguen pudiendo mostrarse como **REVISAR / CON RIESGO**, pero no se confunden con APOSTAR.

## Filosofía

V7.6 no intenta inflar probabilidades ni producir más picks verdes. Busca reducir falsos verdes y hacer que una recomendación pregame tenga suficientes datos detrás.

## Importante

Sigue siendo una versión Alpha. Statcast/Savant puede no estar disponible para todos los jugadores o consultas; cuando falla, el modelo conserva el fallback MLB. Esto no sustituye backtesting ni calibración con una muestra amplia de Paper Bets.
