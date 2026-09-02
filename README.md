# MLB Betting Hub — V7.2 Alpha

V7.2 rediseña el flujo para responder una pregunta: **¿qué puedo apostar AHORA entre los juegos que todavía no empiezan?**

## Cambios principales

- Se elimina la pestaña **Analista experto**.
- Se elimina la pestaña independiente **Línea editable**.
- La edición de línea ahora vive dentro de cada recomendación de **Express**. Si Draftea ofrece otra línea, se cambia ahí y V7.2 recalcula la probabilidad para esa línea antes de evaluar el momio.
- Express vuelve a revisar el estado de la jornada en cada búsqueda y excluye juegos `Live` o `Final`.
- Filtro de lineups: **Solo completos** o **Completos o pendientes**.
- Tres objetivos de búsqueda:
  - 🛡️ Alta probabilidad: prioriza probabilidad conservadora, confianza y baja volatilidad; no exige momio de referencia para existir.
  - ⚖️ Balanceado: mezcla robustez y precio.
  - 💰 Mejor valor: exige precio de referencia y busca EV.
- Se reemplaza “Máx. props” por **Diversificación automática**. Es un límite blando: evita que todo el Top sean jugadores, pero no mete picks débiles solo para completar variedad.
- Express trabaja en dos pasos: pre-filtro de juegos/lineups y análisis solo de los elegibles.
- Se agregan F5 ML y Full Game totals al pool Express para aumentar variedad de mercados.
- Mejor simulación de bateadores: el Total Bases ya no usa solo Poisson; se simula perfil de 1B/2B/3B/HR por aparición al plato con regresión a la media. HRR incorpora OBP/SLG como ajuste acotado.
- Cada pick muestra **Probabilidad central, conservadora, confianza y riesgo** por separado.
- Paper Betting ya no depende únicamente de `st.session_state`: existe respaldo JSON local para sobrevivir F5/reruns en la misma instancia. Si Supabase está configurado, se usa como persistencia externa real.
- Los momios de referencia siguen siendo opcionales para Alta Probabilidad y necesarios para el modo Mejor Valor.

## Importante sobre Paper Betting

El respaldo local resuelve el borrado por F5/rerun mientras la instancia de Streamlit siga viva. Streamlit Community Cloud puede reiniciar/recrear el servidor, así que para persistencia permanente se recomienda Supabase.

### Streamlit Secrets

```toml
ODDS_API_KEY = "..."
SUPABASE_URL = "https://TU_PROYECTO.supabase.co"
SUPABASE_KEY = "TU_ANON_KEY"
```

Ejecuta `supabase_schema.sql` una sola vez en Supabase SQL Editor.

## Filosofía V7.2

- Alta probabilidad **no significa apuesta segura**.
- No se fuerza un Top 10 si solo hay 4 o 6 picks que cumplen.
- La línea debe coincidir exactamente con la probabilidad evaluada.
- El precio ayuda a decidir, pero el modo Alta Probabilidad puede descubrir picks sin depender 100% de momios.
- La meta es mejorar calibración y selección; no se promete un porcentaje fijo como 13/16.

## Instalación

Sube/reemplaza en GitHub:

- `app.py`
- `requirements.txt`
- `README.md`
- `supabase_schema.sql`
- `.streamlit_secrets_example.toml`

Streamlit Community Cloud redeploya desde `main`.
