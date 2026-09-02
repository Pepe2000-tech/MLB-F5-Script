# MLB Betting Hub — V7.6.2 Alpha

## Qué cambia frente a V7.6.1

### Paper Bets
- Ahora puedes borrar **una Paper Bet individual** con confirmación, sin limpiar toda la lista.
- Express tiene botón/expander para guardar directamente una selección en Paper Bets.
- Parlays tiene opción para guardar sus piernas directamente en Paper Bets, unidas por un ID de parlay.
- Se guardan metadatos de origen (`EXPRESS`, `PARLAY` o manual), línea, lado, familia de mercado y calidad.
- La liquidación automática usa esos datos estructurados, por lo que una línea editada puede seguir resolviéndose correctamente.

### Express
- Al editar lado, línea o momio, el botón ahora dice **Aplicar cambio y actualizar TODO Express**.
- Recalcula: probabilidad central, conservadora, confianza, riesgo, confiabilidad del mercado, Bet Quality, Gate y ranking de Express.
- También reconstruye el Top/fallback y la vista de ganador Full Game ML.

### Parlays
- Sigue siendo independiente de Express y analiza toda la jornada elegible.
- Cada pierna permite editar línea/lado/momio cuando el mercado lo soporta.
- Nuevo botón **Actualizar TODO el parlay con mis cambios**.
- Recalcula cada pierna y después actualiza momio combinado y probabilidad conjunta conservadora.
- Paper Betting guarda las piernas por separado para que MLB pueda liquidarlas individualmente, conservando un mismo ID de grupo de parlay.

## Persistencia
- Sin Supabase: respaldo local para reruns en la misma instancia.
- Con Supabase: Paper Bets sobreviven reinicios/redeploys.

## Importante
V7.6.2 sigue siendo una versión Alpha para validación/Paper Betting. Alta probabilidad no significa apuesta segura.
