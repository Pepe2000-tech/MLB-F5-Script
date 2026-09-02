# MLB Betting Hub V7.6.5 Alpha — Draftea Market Normalizer

V7.6.5 reconstruye la capa de mercados de jugador/pitcher para que el modelo deje de premiar líneas teóricas extremas que no corresponden a lo que el usuario realmente ve en Draftea.

## Cambios principales

### 1. Memoria de líneas reales de Draftea
Cuando corriges una línea de Pitcher Ks o un prop de bateador, la app guarda la línea por fecha + partido + jugador + familia de mercado.

Ejemplo:

- Modelo estimado: Pitcher X Over 6.5 K
- Draftea real: 3.5 K
- V7.6.5 guarda Pitcher X / Ks = 3.5
- Al volver a ejecutar Express o analizar el partido, se recalculan Over y Under usando 3.5. Ya no reaparecen 4.5, 5.5 o 6.5 para ese mismo jugador/mercado durante esa jornada.

La línea guardada NO fija la apuesta. El pick vuelve a competir contra todos los demás con su nueva probabilidad, confianza, Bet Quality, Gate y ranking.

### 2. Pitcher Ks sin línea conocida
Mientras todavía no se ha informado la línea de Draftea, el motor deja de meter todas las líneas alternas al ranking. Usa una sola línea central estimada y la marca como pendiente de confirmación.

Esto evita recomendaciones como Under 7.5 únicamente porque una línea extrema produce una probabilidad artificialmente alta.

### 3. Props de bateador en lenguaje Draftea
Hits, Total Bases, HRR y Home Run se presentan como hitos enteros:

- 1+ Hits
- 2+ Hits
- 3+ Hits

Internamente el modelo sigue calculando con la distribución completa. Por ejemplo, 3+ Hits corresponde matemáticamente a superar 2.5, pero la interfaz ya no obliga al usuario a traducirlo.

### 4. Exclusión de apuestas contradictorias
El Top ya no puede utilizar dos lugares para lados mutuamente excluyentes del mismo mercado.

Ejemplo:

- Yankees Full Game ML
- Red Sox Full Game ML

El modelo puede calcular ambos, pero solo el mejor lado puede aparecer como selección del Top. Si se solicitan dos apuestas, la segunda debe venir de otro mercado compatible o de otro partido; si no hay suficiente calidad, se muestran menos selecciones.

También se evita duplicar Over/Under del mismo total y múltiples alternativas del mismo jugador + familia de mercado.

### 5. Express y Partido usan las mismas líneas
Las líneas guardadas se aplican tanto en Express como al analizar un partido individual. En Partido se añadió un control para informar la línea Draftea y recalcular.

### 6. Parlays alineados
Los parlays utilizan el mismo normalizador porque nacen del mismo motor de jornada. Al editar un prop en Parlay también se recuerda la línea Draftea para posteriores análisis de esa jornada.

### 7. Momios de referencia no pisan Draftea
Si una línea real de Draftea ya fue informada y la API de momios de referencia encuentra una línea distinta, V7.6.5 conserva Draftea. La referencia externa no sustituye silenciosamente la línea manual.

## Se mantiene de V7.6.4.1

- Paper Parlays completos: un parlay = una Paper Bet.
- Multi-Parlays independientes.
- Perfiles Menor riesgo / Equilibrado / Mayor ganancia.
- Paper Bets individuales desde Express.
- Eliminación individual de Paper Bets.
- Statcast/Savant.
- Bet Quality, calibración y Pre-Bet Gate.
- Exclusión de juegos iniciados/finalizados.
- Hotfix de Evaluar Momios.

## Persistencia de líneas

Las líneas Draftea se guardan en memoria de sesión y en un respaldo local de la instancia Streamlit. Esto permite reutilizarlas al volver a ejecutar Express durante la jornada en la misma instancia. No se considera almacenamiento permanente tras un redeploy/reinicio del servidor.
