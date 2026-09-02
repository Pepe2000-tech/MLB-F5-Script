# MLB Betting Hub V7.6.7 Alpha — Calibrated Prop Ladder

Esta versión parte de V7.6.6 y mantiene sus protecciones: Express selectivo, menú rápido, F5 limitado a Over 4.5 / Under 5.5, líneas Draftea recordadas, exclusión automática de selecciones ya guardadas en Paper Bets, Multi-Parlays y Paper Parlays completos.

## Cambios V7.6.7

### 1. Probability Guard
El motor conserva la probabilidad cruda de la simulación, pero antes del ranking aplica una capa preventiva de calibración que reduce sobreconfianza según calidad de datos, confiabilidad del mercado, acuerdo entre modelos, lineups y volatilidad. La probabilidad cruda queda guardada para auditoría.

Esto no garantiza mayor acierto: busca que un 70–80% sólo sobreviva como tal cuando la evidencia del mercado realmente sea fuerte.

### 2. Prop Ladder 1+ / 2+ / 3+
Hits, Total Bases y HRR ya no se reducen automáticamente a un único escalón. El analizador conserva 1+, 2+, 3+ (y 4+ donde exista en la simulación) para comparar internamente el riesgo adicional.

La salida principal sigue favoreciendo las selecciones conservadoras, pero Express añade una sección separada `Escalón + riesgo` para mostrar 2+/3+ cuando la distribución mantiene suficiente señal.

### 3. No se disfraza 2+ como apuesta segura
Las alternativas de escalón superior se muestran aparte y con su probabilidad ajustada/conservadora. No se convierten en verde sólo por pagar más o por ser más agresivas.

### 4. Auditoría de probabilidades
En el análisis detallado se puede comparar `Cruda` vs `Ajustada`, lo que facilita detectar si el modelo estaba siendo demasiado optimista.

## Archivos
- `app.py`
- `requirements.txt`
- `supabase_schema.sql`
- `.streamlit_secrets_example.toml`

## Despliegue
Reemplaza los archivos de la versión anterior en GitHub y haz commit a `main`. Streamlit Community Cloud debería volver a desplegar automáticamente.
