# MLB Betting Hub V6.5.3 — FINAL DE PRUEBAS

Esta es la versión para congelar el algoritmo y comenzar el bloque formal de Paper Betting.

## Cambios sobre V6.5.2
- No cambia el motor estadístico.
- Corrige el estado visual:
  - pitcher confirmado
  - lineup rival pendiente/confirmado
  - predicción provisional/final
- Al congelar guarda:
  - hora exacta CDMX
  - timestamp ISO
  - horas que faltaban para iniciar el juego
  - estado de ambos lineups
  - cantidad de bateadores disponibles por lineup
- Paper Betting muestra:
  - FINAL o PRELIMINAR
  - estado de lineups al congelar
  - hora de congelación
  - horas antes del partido
- Dashboard compara:
  - FINAL vs PRELIMINAR
  - con lineups confirmados vs con lineups pendientes
- CSV exporta toda la trazabilidad nueva.

## Regla de prueba
No modificar algoritmo, pesos ni fórmulas durante el bloque.
Objetivo inicial: 100–200 Paper Bets antes de una recalibración seria.
