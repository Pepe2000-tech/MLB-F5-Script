# MLB Betting Hub — V7.6.9 Alpha

## Nuevo: ✍️ F5 Manual x4

La pestaña F5 Manual ahora deja claro qué partido está siendo analizado y permite capturar hasta **4 líneas F5 reales de Draftea** al mismo tiempo.

### Cómo usarlo
1. Selecciona fecha y partido en la parte superior.
2. Abre **✍️ F5 Manual**.
3. Verifica el bloque **Partido seleccionado**.
4. Captura hasta 4 líneas F5 y los momios Over/Under de cada una.
5. Puedes desactivar filas que Draftea no tenga.
6. Pulsa **🧠 Analizar las líneas F5**.

El sistema compara hasta **8 opciones** (Over y Under de cada línea) sobre la misma simulación del partido, y las ordena por veredicto, EV conservador y probabilidad conservadora.

### Resultado rápido
Primero muestra una salida corta con la mejor F5 encontrada y después una lista ordenada de todas las alternativas. El análisis técnico completo queda dentro de **🔬 Ver análisis detallado de las opciones**.

### Mantiene el motor avanzado
- proyección F5 por equipo;
- abridores y forma reciente;
- lineups;
- parque y clima cuando están disponibles;
- Monte Carlo con incertidumbre;
- submodelos F5;
- calibración de Paper Bets cuando existe muestra suficiente;
- probability guard V7.6.7;
- probabilidad ajustada y conservadora;
- momio justo y EV conservador;
- confianza, Market Reliability y Bet Quality.

Cada alternativa puede guardarse individualmente en Paper Bets con la línea y momio exactos capturados.

## Importante
Express conserva sus reglas propias. F5 Manual analiza exactamente las líneas que el usuario ve en Draftea y no inventa otras.

## Actualización
Reemplaza en GitHub los archivos de esta carpeta y haz commit en `main`. Streamlit debería redeployar automáticamente.
