# MLB Betting Hub V6.1

V6.1 conserva el motor y la interfaz de V6 y agrega horario de inicio de los partidos en hora de Ciudad de México.

## Nuevo
- El selector de partido muestra: `EQUIPO @ EQUIPO — HORA CDMX`.
- El bloque `Contexto del partido` muestra también la hora de inicio CDMX.
- La conversión usa la zona `America/Mexico_City`, por lo que no se usa un desplazamiento fijo manual.
- No se cambia la lógica estadística ni las recomendaciones de V6.

# MLB Betting Hub V6

V6 conserva el flujo sencillo de V5.1 y añade una capa de análisis tipo "analista experto".

## Mejoras V6
- Contexto visible de pitchers, clima, estadio y lineups.
- Posición defensiva en lineup cuando MLB la publica; identifica catcher.
- Bullpen reciente con pitch counts reales de relevistas en los 3 días previos cuando StatsAPI lo permite.
- Brazos cargados: identifica relevistas con uso elevado reciente.
- Full Game incorpora la carga reciente del bullpen al proxy.
- Matchup de pitcher Ks pondera K-rate de cada bateador según el orden al bat.
- Nueva pestaña `Analista experto`:
  - lectura principal
  - factores a favor
  - riesgos
  - qué evitar
  - consenso del sistema
- Ranking sigue usando probabilidad central, conservadora, incertidumbre, calidad y acuerdo.
- Historial guarda también categoría y acuerdo de modelos.

## Qué NO hace V6
- No inventa Statcast.
- Todavía no usa xwOBA/xSLG/Barrel/Hard-Hit directamente.
- No conoce lesiones o noticias no publicadas en MLB StatsAPI.
- La capa "analista experto" interpreta reglas/evidencia; no es un LLM externo.

## Siguiente capa recomendada
1. Statcast fiable y cacheado.
2. Noticias/lesiones/contexto pregame.
3. Backtesting persistente y resultados automáticos.
4. Calibración por mercado.

