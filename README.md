# MLB Betting Hub — V7.1.1 Alpha

V7.1.1 agrega **momios de referencia automáticos** a la arquitectura V7.

## Qué cambia en V7.1.1

- Integra The Odds API usando `baseball_mlb`.
- Consulta cuotas en formato decimal.
- Usa mercado US como referencia (`regions=us`).
- Para cada pick puede mostrar:
  - mediana de momios entre casas disponibles;
  - mejor momio encontrado y casa;
  - número de casas usadas;
  - línea de mercado encontrada;
  - EV conservador contra ese precio;
  - veredicto APOSTAR / CANDIDATO / PASS.
- Si la API ofrece una línea distinta a la recomendada por el modelo, V7.1.1 recalcula la probabilidad sobre la línea de mercado antes de evaluar el precio.
- El momio de Draftea sigue siendo editable manualmente y tiene prioridad para la decisión final.
- Modo Express consulta momios sólo para un pool corto de candidatos para reducir consumo de créditos.
- El constructor de parlays usa el momio de referencia como valor inicial cuando existe.

## Mercados de referencia conectados

- F5 Totals: `alternate_totals_1st_5_innings`
- Full Game Totals: `totals`
- Pitcher strikeouts: `pitcher_strikeouts`
- Batter hits: `batter_hits`
- Batter total bases: `batter_total_bases`
- Hits + Runs + RBIs: `batter_hits_runs_rbis`
- Batter home runs: `batter_home_runs`

## Configuración

En Streamlit Community Cloud abre:

`App > Settings > Secrets`

y agrega:

```toml
ODDS_API_KEY = "TU_API_KEY"
```

No coloques la llave real dentro de `app.py` ni la subas a GitHub.

## Uso recomendado

1. Abre **⚡ Express**.
2. Selecciona cuántas apuestas quieres buscar.
3. Pulsa **Analizar toda la jornada**.
4. V7.1.1 calcula primero el modelo y después consulta precios sólo para candidatos preseleccionados.
5. Express prioriza picks cuyo precio de referencia tenga valor según la probabilidad conservadora.
6. En Draftea, sustituye el momio de referencia por el momio real si es diferente.
7. En **✏️ Línea editable**, puedes consultar una cuota de referencia específica y recalcular una línea alternativa.

## Importante

El momio mostrado es una **referencia de mercado**, no una cuota de Draftea ni una garantía de disponibilidad. Las casas pueden mover líneas y precios rápidamente.

La API utiliza créditos por mercados/regiones consultados. V7.1.1 agrupa mercados por juego y limita el pool consultado para evitar gasto innecesario. La pantalla Express muestra los créditos restantes cuando la API los devuelve.

## Persistencia

Supabase sigue siendo opcional. Consulta `supabase_schema.sql` y `.streamlit_secrets_example.toml`.


## V7.1.1 hotfix LIVE
- Corrige el endpoint de MLB `feed/live` de `/api/v1` a `/api/v1.1`.
- Añade estado LIVE, conteo, corredores, pitcher/bateador, pitch count y última jugada cuando MLB los publica.
- No modifica probabilidades, filtros, Monte Carlo, confianza ni lógica de apuestas.
