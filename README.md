# MLB Betting Hub V7.2.5 Alpha

V7.2.5 hace que Express permita elegir mercados concretos en lugar de agruparlos de forma ambigua.

## Cambios de V7.2.5
- **F5 Carreras**: Express analiza únicamente Over/Under de carreras en las primeras 5 entradas. F5 Moneyline deja de formar parte de Express.
- **Full Game ML**: opción independiente para buscar al ganador del partido completo.
- **Full Game Carreras**: opción independiente para buscar Over/Under de carreras del juego completo.
- **Pitcher Ks** y **Batter props** siguen disponibles, pero son opcionales.
- Por defecto Express arranca con **F5 Carreras + Full Game ML + Full Game Carreras**, evitando que props de pitchers aparezcan si el usuario no los activa.
- La diversificación y el máximo de selecciones por partido continúan respetándose.
- Si Full Game ML está activado, se mantiene la vista **Ganador con mayor probabilidad por partido**.
- Si no hay suficientes verdes, Express puede mostrar las mejores alternativas con riesgo claramente identificado.
- Momios de referencia siguen siendo opcionales.
- La edición de línea dentro de Express sigue pasando la selección ajustada a **Evaluar momios**.

## Flujo recomendado
1. Selecciona lineups completos o pendientes.
2. Elige los mercados exactos que quieres analizar.
3. Decide si deseas usar momios de referencia.
4. Ejecuta Express.
5. Edita una línea dentro de la propia tarjeta si Draftea ofrece otra.
6. Revisa la selección ajustada en Evaluar momios.

La aplicación no garantiza resultados ni apuestas seguras; prioriza probabilidad, confianza y riesgo y puede marcar alternativas cuando ninguna opción alcanza el umbral de recomendación.
