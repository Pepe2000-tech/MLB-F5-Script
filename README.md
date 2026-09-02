# MLB Betting Hub — V7.2.2 Alpha

Actualización enfocada en dos problemas detectados durante la prueba de V7.2.1: Express seguía dominado por props de pitchers y el contexto del partido ocupaba demasiado espacio cuando solo se quería usar Express.

## Cambios V7.2.2

- Express ahora conserva candidatos de cada familia **antes** del ranking global.
- Familias: F5/juego, Full Game, Pitcher props y Batter props.
- Nuevo selector **Mercados a incluir**. Puedes desactivar por completo Pitcher props.
- Diversificación automática más estricta. En un Top 10, Pitcher props no puede ocupar más de 2 posiciones; Batter props hasta 3; F5 hasta 4; Full Game hasta 2, siempre que existan picks que superen filtros.
- Si una familia no tiene candidatos suficientemente sólidos, V7 devuelve menos apuestas. No rellena con selecciones peores para completar el número solicitado.
- Auditoría del submodelo Pitcher K:
  - mayor regresión de innings esperados,
  - límites más conservadores para skill/matchup,
  - mayor dispersión de Ks,
  - lineup rival pendiente reduce agreement, calidad y confirmación,
  - la predicción de K deja de tratarse como completamente confirmada cuando el lineup rival no lo está.
- El contexto del partido queda colapsado por defecto en **Ver contexto del partido seleccionado**. Express sigue usando esos datos automáticamente.
- Momios continúan siendo opcionales en Express.
- La edición de línea/momio dentro del Top sigue propagándose a **Evaluar momios**.
- Paper Betting mantiene el respaldo local/Supabase preparado de V7.2.1.

## Importante

V7.2.2 no promete apuestas seguras ni una tasa fija de acierto. El objetivo es ser más selectivo, evitar concentración artificial en una familia y mostrar menos picks cuando no existen suficientes candidatos robustos.
