# MLB Betting Hub — V7.6.8 Alpha

## Nuevo: ✍️ F5 Manual

Esta versión recupera la idea del primer MVP: tú escribes manualmente el mercado que realmente ves en Draftea y el sistema analiza esa apuesta exacta.

### Cómo usar F5 Manual
1. Selecciona la fecha y el partido arriba.
2. Abre la pestaña **✍️ F5 Manual**.
3. Captura la **línea F5 real de Draftea**.
4. Captura el **momio Over** y el **momio Under** en formato decimal.
5. Pulsa **🧠 Analizar línea F5 manual**.

La pestaña compara ambos lados usando el motor avanzado actual:
- proyección F5 por equipo;
- abridores y forma reciente;
- lineups;
- parque y clima cuando están disponibles;
- Monte Carlo con incertidumbre;
- submodelos de F5;
- calibración de Paper Bets cuando ya existe muestra suficiente;
- probability guard V7.6.7;
- probabilidad ajustada y conservadora;
- momio justo;
- EV conservador;
- confianza, Market Reliability y Bet Quality.

El resultado final queda simplificado como **APOSTAR / CANDIDATO / PASS** y puedes guardar directamente la selección en Paper Bets con la línea y momio exactos.

## Importante
La pestaña automática Express sigue limitada a F5 Over 4.5 / Under 5.5. **F5 Manual no tiene esa limitación**, porque su propósito es analizar exactamente la línea que el usuario introduce desde Draftea.

## Actualización
Reemplaza en GitHub los archivos de esta carpeta y haz commit en `main`. Streamlit debería redeployar automáticamente.
