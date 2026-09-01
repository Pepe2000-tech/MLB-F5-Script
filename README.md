# MLB F5 Model — V2

## Cambios de V2
- Cartelera MLB automática por fecha.
- Equipos automáticos.
- Pitchers probables automáticos cuando MLB los publica.
- Runs Per Game de temporada.
- Runs Per Game de últimos 15 juegos.
- ERA y WHIP del pitcher abridor.
- Proyección F5 automática.
- Poisson para probabilidad Over/Under.
- Probabilidad F5 visitante/local/empate.
- Comparación contra momios.
- Fair odds.
- PASS / LEAN / PLAY / STRONG PLAY.
- Penalización de confianza cuando falta pitcher o hay poca muestra.

## Lo que todavía falta
Esta NO es todavía la versión final del modelo.

V3 añadirá:
- splits vs RHP/LHP
- Statcast / Baseball Savant
- xERA, xwOBA, Barrel%, Hard-Hit%
- lineups confirmados
- parque
- clima
- umpire
- calidad del bullpen (para Full Game)
- IA para investigación contextual
- historial y backtesting

## Actualizar la app en GitHub
Reemplaza los archivos actuales del repositorio por:
- app.py
- data_mlb.py
- model.py
- requirements.txt
- README.md

Streamlit redeployará automáticamente después del commit.
