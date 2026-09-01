# MLB Betting Hub V6.5.2

Mejora de interfaz para Paper Betting:

- Sustituye `Unidades paper` por `Monto simulado de apuesta (MXN)`.
- Muestra en pantalla:
  - Apuesta simulada
  - Cobro total si gana
  - Ganancia neta si gana
  - Pérdida simulada si falla
- Internamente se conserva la equivalencia de unidades:
  - 1 unidad = $50 MXN
- El CSV guarda pesos y unidades.
- El dashboard calcula ROI y ganancia paper en MXN.

El motor estadístico de V6.5.1 no fue modificado.
