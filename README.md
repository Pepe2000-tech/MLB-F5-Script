# MLB Betting Hub — V7.2.1 Alpha

V7.2.1 simplifica Express para el objetivo principal: **encontrar las apuestas más robustas disponibles AHORA**, sin obligar al usuario a escoger entre “valor”, “balanceado” o “alta probabilidad”.

## Qué cambia

- Se elimina el selector **Objetivo** de Express. V7.2.1 prioriza automáticamente probabilidad conservadora, confianza, incertidumbre y riesgo.
- Nuevo interruptor **Usar momios de referencia**:
  - apagado: Express trabaja solo con el modelo y no consume créditos de The Odds API;
  - encendido: el precio de mercado también entra como filtro secundario.
- Diversificación más fuerte: máximo aproximado de 50% props, 30% pitcher props y 30% batter props. Si no hay variedad suficiente, devuelve menos apuestas en vez de llenar el Top con pitchers.
- Se mantiene el filtro dinámico de juegos: solo partidos que aún no empiezan, con opción de exigir lineups completos o aceptar pendientes.
- **Edición de línea dentro del Top Express**: si Draftea tiene otra línea, se recalcula la probabilidad para esa línea exacta.
- Nuevo botón **Usar esta línea y momio**: el ajuste queda guardado en el Top y pasa ya corregido a **Evaluar momios**.
- **Evaluar momios** usa primero el Top Express actual. Si un pick fue ajustado, abre con la línea y momio Draftea ya guardados.
- Paper Betting ahora llama a la capa de persistencia al momento de congelar. Esto corrige el caso donde se añadía al `session_state` pero no se escribía al respaldo.
- Con Supabase configurado, los Paper Bets sobreviven reinicios/redeploys. Sin Supabase, el respaldo local ayuda con F5/reruns de la misma instancia, pero Streamlit Community Cloud puede recrear el servidor.
- Se mantiene el fix de coincidencia de línea: jamás se usa la probabilidad de O2.5 con el momio de O4.5.

## Filosofía

V7.2.1 busca **mayor probabilidad y menor riesgo**, pero ninguna apuesta es “segura” ni se garantiza ganar. Si el usuario pide 10 y solo 4 cumplen, devuelve 4.

## Streamlit Secrets

```toml
ODDS_API_KEY = "..."
SUPABASE_URL = "https://TU_PROYECTO.supabase.co"
SUPABASE_KEY = "TU_ANON_KEY"
```

La API de momios es opcional para Express. Para persistencia permanente de Paper Betting, Supabase sí debe configurarse.

## Instalación

Sube/reemplaza en GitHub:

- `app.py`
- `requirements.txt`
- `README.md`
- `supabase_schema.sql`

Streamlit Community Cloud redeploya desde `main`.
