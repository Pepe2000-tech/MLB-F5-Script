
# MLB F5 Model — MVP

## Qué hace esta versión
- Captura manualmente equipos, pitchers, proyección de carreras F5, línea y momios.
- Convierte momios americanos a probabilidad implícita.
- Usa Poisson para estimar probabilidades de Over/Under.
- Estima probabilidades F5 de visitante/local/empate.
- Calcula edge contra el mercado.
- Clasifica el pick como STRONG PLAY / PLAY / LEAN / PASS.

## Cómo correrlo en tu computadora

1. Instala Python 3.11 o superior.
2. Abre una terminal dentro de esta carpeta.
3. Ejecuta:

   pip install -r requirements.txt

4. Luego:

   streamlit run app.py

5. Se abrirá en tu navegador, normalmente en:

   http://localhost:8501

## Cómo subirlo a Streamlit Community Cloud

1. Crea una cuenta en GitHub.
2. Crea un repositorio nuevo.
3. Sube:
   - app.py
   - model.py
   - requirements.txt
4. Entra a Streamlit Community Cloud.
5. Elige "Create app".
6. Conecta tu repositorio de GitHub.
7. Selecciona app.py como archivo principal.
8. Deploy.

## Próxima versión
- Cartelera MLB automática.
- Pitchers probables.
- Splits vs RHP/LHP.
- Estadísticas avanzadas.
- Clima.
- Lineups confirmados.
- Odds.
- Capa IA.
- Historial y backtesting.
