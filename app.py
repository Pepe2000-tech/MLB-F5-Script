from datetime import date
import streamlit as st

from data_mlb import (
    get_schedule,
    get_team_form,
    get_pitcher_stats,
    get_weather,
    get_stadium_context,
)
from model import (
    project_f5_runs_v3,
    total_probabilities,
    moneyline_probabilities,
    no_vig_probs,
    expected_value_decimal,
    prob_to_decimal,
    grade_pick,
)

st.set_page_config(page_title="MLB F5 Model V3", page_icon="⚾", layout="centered")

st.title("⚾ MLB F5 Model — V3")
st.caption("Primeras 5 entradas • Datos MLB + abridores + parque + clima + comparación de mercados")

selected_date = st.date_input("📅 Fecha", value=date.today())
games = get_schedule(selected_date.isoformat())

if not games:
    st.warning("No encontré partidos MLB para esta fecha o la fuente no respondió.")
    st.stop()

game_label = st.selectbox("⚾ Partido", [g["label"] for g in games])
game = next(g for g in games if g["label"] == game_label)

with st.spinner("Consultando datos MLB y contexto..."):
    away_form = get_team_form(game["away_id"], selected_date.isoformat())
    home_form = get_team_form(game["home_id"], selected_date.isoformat())

    away_pitch = get_pitcher_stats(game["away_pitcher_id"], selected_date.year) if game["away_pitcher_id"] else None
    home_pitch = get_pitcher_stats(game["home_pitcher_id"], selected_date.year) if game["home_pitcher_id"] else None

    park = get_stadium_context(game["home_abbr"])
    weather = get_weather(
        park["lat"],
        park["lon"],
        selected_date.isoformat(),
        game.get("game_time_local")
    ) if park else None

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader(f"✈️ {game['away_abbr']}")
    st.write(f"**Pitcher:** {game['away_pitcher_name']}")
    st.caption(f"RPG temporada {away_form['season_rpg']:.2f} | últimos 15 {away_form['recent_rpg']:.2f}")
    if away_pitch:
        st.caption(
            f"ERA {away_pitch['era']:.2f} | WHIP {away_pitch['whip']:.2f} | "
            f"K/9 {away_pitch['k9']:.2f} | BB/9 {away_pitch['bb9']:.2f} | HR/9 {away_pitch['hr9']:.2f}"
        )

with c2:
    st.subheader(f"🏠 {game['home_abbr']}")
    st.write(f"**Pitcher:** {game['home_pitcher_name']}")
    st.caption(f"RPG temporada {home_form['season_rpg']:.2f} | últimos 15 {home_form['recent_rpg']:.2f}")
    if home_pitch:
        st.caption(
            f"ERA {home_pitch['era']:.2f} | WHIP {home_pitch['whip']:.2f} | "
            f"K/9 {home_pitch['k9']:.2f} | BB/9 {home_pitch['bb9']:.2f} | HR/9 {home_pitch['hr9']:.2f}"
        )

st.subheader("🏟️ Contexto automático")
cc1, cc2, cc3 = st.columns(3)
cc1.metric("Park factor", f"{park['factor']:.2f}" if park else "N/D")
cc2.metric("Temperatura", f"{weather['temp_f']:.0f}°F" if weather else "N/D")
cc3.metric("Viento", f"{weather['wind_mph']:.0f} mph" if weather else "N/D")

if weather:
    st.caption(
        f"Clima: {weather['summary']} | Humedad {weather['humidity']:.0f}% | "
        f"Viento {weather['wind_mph']:.1f} mph"
    )

away_proj, away_debug = project_f5_runs_v3(
    offense=away_form,
    opposing_pitcher=home_pitch,
    park_factor=park["factor"] if park else 1.0,
    weather=weather,
)

home_proj, home_debug = project_f5_runs_v3(
    offense=home_form,
    opposing_pitcher=away_pitch,
    park_factor=park["factor"] if park else 1.0,
    weather=weather,
)

total_proj = away_proj + home_proj
ml_probs = moneyline_probabilities(away_proj, home_proj)

st.divider()
st.subheader("🎰 Mercados F5")
st.caption("Cuotas decimales. Captura solo lo que aparezca en Draftea.")

with st.expander("⚾ Money Line F5", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        away_ml = st.number_input(f"{game['away_abbr']} ML", 1.01, 20.0, 1.80, .01, format="%.2f")
    with c2:
        home_ml = st.number_input(f"{game['home_abbr']} ML", 1.01, 20.0, 2.00, .01, format="%.2f")

with st.expander("📊 Total F5 — Línea 1", expanded=True):
    l1, l2, l3 = st.columns(3)
    with l1:
        line1 = st.number_input("Línea 1", 2.5, 8.5, 4.5, .5)
    with l2:
        over1 = st.number_input("Over 1", 1.01, 20.0, 1.90, .01, format="%.2f")
    with l3:
        under1 = st.number_input("Under 1", 1.01, 20.0, 1.90, .01, format="%.2f")

with st.expander("📊 Total F5 — Línea 2", expanded=False):
    use2 = st.checkbox("Comparar línea 2")
    a,b,c = st.columns(3)
    with a:
        line2 = st.number_input("Línea 2", 2.5, 8.5, 5.5, .5)
    with b:
        over2 = st.number_input("Over 2", 1.01, 20.0, 2.10, .01, format="%.2f")
    with c:
        under2 = st.number_input("Under 2", 1.01, 20.0, 1.75, .01, format="%.2f")

with st.expander("📊 Total F5 — Línea 3", expanded=False):
    use3 = st.checkbox("Comparar línea 3")
    a,b,c = st.columns(3)
    with a:
        line3 = st.number_input("Línea 3", 2.5, 8.5, 6.5, .5)
    with b:
        over3 = st.number_input("Over 3", 1.01, 20.0, 2.40, .01, format="%.2f")
    with c:
        under3 = st.number_input("Under 3", 1.01, 20.0, 1.55, .01, format="%.2f")

if st.button("🚀 Analizar todos los mercados F5", use_container_width=True):
    candidates = []

    # F5 ML: tratamos ML de 2 vías como empate = push, por eso condicionamos a no empate.
    no_tie = ml_probs["away"] + ml_probs["home"]
    p_away_ml = ml_probs["away"]/no_tie if no_tie else .5
    p_home_ml = ml_probs["home"]/no_tie if no_tie else .5

    nv_away, nv_home, _ = no_vig_probs(away_ml, home_ml)

    candidates.append({
        "market": f"{game['away_abbr']} F5 ML",
        "p": p_away_ml,
        "odds": away_ml,
        "edge": p_away_ml - nv_away,
        "ev": expected_value_decimal(p_away_ml, away_ml),
    })
    candidates.append({
        "market": f"{game['home_abbr']} F5 ML",
        "p": p_home_ml,
        "odds": home_ml,
        "edge": p_home_ml - nv_home,
        "ev": expected_value_decimal(p_home_ml, home_ml),
    })

    def add_total(line, over_odds, under_odds):
        probs = total_probabilities(total_proj, line)
        nv_u, nv_o, _ = no_vig_probs(under_odds, over_odds)

        candidates.append({
            "market": f"F5 UNDER {line:g}",
            "p": probs["under"],
            "odds": under_odds,
            "edge": probs["under"] - nv_u,
            "ev": expected_value_decimal(probs["under"], under_odds),
        })
        candidates.append({
            "market": f"F5 OVER {line:g}",
            "p": probs["over"],
            "odds": over_odds,
            "edge": probs["over"] - nv_o,
            "ev": expected_value_decimal(probs["over"], over_odds),
        })

    add_total(line1, over1, under1)
    if use2:
        add_total(line2, over2, under2)
    if use3:
        add_total(line3, over3, under3)

    data_quality = 100
    if not game["away_pitcher_id"] or not game["home_pitcher_id"]:
        data_quality -= 25
    if away_pitch is None or home_pitch is None:
        data_quality -= 20
    if weather is None:
        data_quality -= 10
    if park is None:
        data_quality -= 5
    data_quality = max(30, min(100, data_quality))

    ranked = sorted(candidates, key=lambda x: x["ev"], reverse=True)
    best = ranked[0]
    verdict, pick_conf = grade_pick(best["ev"], best["edge"], data_quality)

    st.divider()
    st.subheader("🤖 Proyección F5 V3")
    p1,p2,p3 = st.columns(3)
    p1.metric(game["away_abbr"], f"{away_proj:.2f}")
    p2.metric(game["home_abbr"], f"{home_proj:.2f}")
    p3.metric("Total F5", f"{total_proj:.2f}")

    st.subheader("🏆 Ranking de mercados")
    for i, c in enumerate(ranked, start=1):
        st.write(
            f"**{i}. {c['market']} @ {c['odds']:.2f}x** — "
            f"Modelo {c['p']*100:.1f}% | Edge {c['edge']*100:+.1f} pp | EV {c['ev']*100:+.1f}%"
        )

    st.subheader("🎯 Recomendación")
    if verdict == "PASS":
        st.info("⚪ PASS — Ningún mercado supera los filtros de valor y confianza.")
    elif verdict == "LEAN":
        st.warning(f"🟡 LEAN: {best['market']} @ {best['odds']:.2f}x")
    elif verdict == "PLAY":
        st.success(f"🟢 PLAY: {best['market']} @ {best['odds']:.2f}x")
    else:
        st.success(f"🔥 STRONG PLAY: {best['market']} @ {best['odds']:.2f}x")

    st.write(f"**Cuota justa estimada:** {prob_to_decimal(best['p']):.2f}x")
    st.write(f"**Calidad de datos:** {data_quality}/100")
    st.write(f"**Confianza del pick:** {pick_conf}")

    with st.expander("🔬 Ver factores del modelo"):
        st.json({
            game["away_abbr"]: away_debug,
            game["home_abbr"]: home_debug,
            "park": park,
            "weather": weather,
        })

st.divider()
st.caption(
    "V3 experimental. Aún falta calibración histórica, lineups confirmados, splits R/L y Statcast. "
    "No garantiza resultados ni ganancias."
)
