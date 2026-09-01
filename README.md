# MLB Betting Hub — V4

V4 convierte el proyecto en un comparador de oportunidades por partido.

## Pestaña principal: Mejor apuesta
Compara solamente mercados que el usuario haya capturado con cuota:
- F5 ML
- hasta 3 totales F5
- Full Game ML
- Full Game total
- hasta 3 player props

Devuelve:
- ranking general
- probabilidad del modelo
- EV
- cuota justa
- cuota mínima objetivo
- PASS / LEAN / PLAY / STRONG

## F5
Mantiene el motor más desarrollado:
- abridores
- ofensiva
- lineups
- parque
- clima

## Full Game
Ahora separa claramente:
- proyección del modelo
- línea de Draftea
- diferencia
- rango central de carreras

Añade bullpen/staff proxy:
- ERA del staff
- WHIP del staff
- carreras permitidas por juego en últimos 10

Sigue siendo BETA y no puede marcar STRONG.

## Props
Genera:
- Pitcher Ks milestones
- Pitcher Ks Over/Under
- Hits milestones y O/U
- Total Bases milestones y O/U
- HRR
- Home Run

Muestra cuota justa y cuota mínima objetivo (~5% EV).
Props de bateadores quedan provisionales sin lineup oficial.

## Próxima etapa recomendada
- Statcast (xwOBA, Barrel%, Hard-Hit%, xERA)
- bullpen real por relevistas disponibles
- backtesting y calibración histórica
