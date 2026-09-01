# MLB Betting Hub V5

V5 cambia el motor estadístico manteniendo la interfaz simple.

## Motor nuevo
- Regresión a la media para ofensiva, pitchers y props.
- Ensemble de 3 submodelos F5:
  - conservador
  - balanceado
  - sensible a forma reciente
- Monte Carlo de 24,000 escenarios.
- Gamma-Poisson para incorporar incertidumbre del parámetro de carreras.
- Probabilidad central + rango plausible.
- Score de confianza 0-100.
- Penalización por:
  - lineups pendientes
  - calidad incompleta
  - desacuerdo entre modelos
  - volatilidad del mercado
- Props de hits con aproximación binomial y tasa regresada.
- Pitcher Ks con K/9 regresado, innings esperados y K-rate rival.
- Full Game sigue usando bullpen/staff proxy y se identifica como BETA.

## Flujo
1. Ver contexto completo.
2. Actualizar datos.
3. Analizar partido.
4. Obtener hasta 5 oportunidades robustas.
5. Evaluar las 5 con momios reales.

V5 no fuerza cinco selecciones si no encuentra suficiente robustez.

## Importante
Esta V5 todavía no está históricamente calibrada.
La siguiente etapa recomendada es guardar predicciones/resultados y hacer backtesting/calibración.
