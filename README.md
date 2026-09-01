# MLB Betting Hub V5.1

Mejoras principales sobre V5:

- Veredicto APOSTAR / LEAN / PASS alineado con EV conservador, cuota objetivo y confianza.
- Resumen de cuántos mercados se analizaron, cuántos pasaron y cuántos se descartaron.
- Sección `Cerca de calificar`.
- Historial básico por sesión + descarga CSV para comenzar backtesting.
- Pitcher Ks mejorados con:
  - K-rate del pitcher cuando está disponible
  - K-rate ponderado del lineup rival
  - innings esperados
  - regresión a la media
- Bullpen/staff proxy mejorado con:
  - ERA / WHIP
  - RA/G últimos 10
  - RA/G últimos 3
  - fatiga proxy
- Mantiene:
  - contexto visible
  - clima
  - estadio
  - pitchers
  - lineups
  - actualizar datos
  - analizar partido
  - Monte Carlo
  - rangos de incertidumbre

Importante:
el historial en Streamlit Community Cloud no es almacenamiento permanente.
Descarga el CSV para conservarlo. La calibración histórica real sigue siendo la siguiente etapa.
