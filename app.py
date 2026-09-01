from datetime import date
import streamlit as st

from data_mlb import get_schedule, get_team_form, get_pitcher_stats
from model import (
    project_f5_runs,
    total_probabilities,
    moneyline_probabilities,
    american_to_implied,
    prob_to_american,
)

st.set_page_config(page_title="MLB F5 Model V2", page_icon="⚾", layout="centered")

st.title("⚾ MLB F5 Model — V2")
st.caption("Cartelera automática + pitchers probables + estadísticas MLB + proyección F5 automática.")

selected_date = st.date_input("📅 Fecha", value=date.today())

games = get_schedule(selected_date.isoformat())

if not games:
    st.warning("No encontré partidos MLB para esta fecha o la fuente no respondió.")
    st.stop()

game_labels = [g["label"] for g in games]
selected_label = st.selectbox("⚾ Selecciona un partido", game_labels)
game = next(g for g in games if g["label"] == selected_label)

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.markdown(f"### ✈️ {game['away_abbr']}")
    st.write(f"**Pitcher:** {game['away_pitcher_name']}")
with c2:
    st.markdown(f"### 🏠 {game['home_abbr']}")
    st.write(f"**Pitcher:** {game['home_pitcher_name']}")

missing_pitcher = not game["away_pitcher_id"] or not game["home_pitcher_id"]
if missing_pitcher:
    st.warning("⚠️ Falta confirmar al menos un pitcher abridor. La confianza del modelo se reducirá.")

season = selected_date.year

with st.spinner("Consultando estadísticas MLB..."):
    away_form = get_team_form(game["away_id"], selected_date.isoformat())
    home_form = get_team_form(game["home_id"], selected_date.isoformat())

    away_pitch = get_pitcher_stats(game["away_pitcher_id"], season) if game["away_pitcher_id"] else None
    home_pitch = get_pitcher_stats(game["home_pitcher_id"], season) if game["home_pitcher_id"] else None

st.subheader("📊 Datos obtenidos")

m1, m2 = st.columns(2)
with m1:
    st.write(f"**{game['away_abbr']} RPG temporada:** {away_form['season_rpg']:.2f}")
    st.write(f"**{game['away_abbr']} RPG últimos 15:** {away_form['recent_rpg']:.2f}")
    if away_pitch:
        st.write(f"**{game['away_pitcher_name']} ERA:** {away_pitch['era']:.2f}")
        st.write(f"**WHIP:** {away_pitch['whip']:.2f}")
    else:
        st.write("**Pitcher visitante:** sin estadísticas")

with m2:
    st.write(f"**{game['home_abbr']} RPG temporada:** {home_form['season_rpg']:.2f}")
    st.write(f"**{game['home_abbr']} RPG últimos 15:** {home_form['recent_rpg']:.2f}")
    if home_pitch:
        st.write(f"**{game['home_pitcher_name']} ERA:** {home_pitch['era']:.2f}")
        st.write(f"**WHIP:** {home_pitch['whip']:.2f}")
    else:
        st.write("**Pitcher local:** sin estadísticas")

st.subheader("🎰 Sportsbook")
s1, s2, s3 = st.columns(3)
with s1:
    f5_line = st.number_input("Línea F5", min_value=0.5, max_value=12.0, value=4.5, step=0.5)
with s2:
    under_odds = st.number_input("Momio Under", value=-110, step=5)
with s3:
    over_odds = st.number_input("Momio Over", value=-110, step=5)

analyze = st.button("🚀 Analizar partido", use_container_width=True)

if analyze:
    away_proj, away_parts = project_f5_runs(
        offense=away_form,
        opposing_pitcher=home_pitch,
        pitcher_confirmed=bool(game["home_pitcher_id"]),
    )
    home_proj, home_parts = project_f5_runs(
        offense=home_form,
        opposing_pitcher=away_pitch,
        pitcher_confirmed=bool(game["away_pitcher_id"]),
    )

    total_proj = away_proj + home_proj

    probs = total_probabilities(total_proj, f5_line)
    ml = moneyline_probabilities(away_proj, home_proj)

    implied_under = american_to_implied(under_odds)
    implied_over = american_to_implied(over_odds)

    edge_under = probs["under"] - implied_under
    edge_over = probs["over"] - implied_over

    best_side = "UNDER" if edge_under >= edge_over else "OVER"
    best_edge = max(edge_under, edge_over)
    best_prob = probs["under"] if best_side == "UNDER" else probs["over"]

    confidence = 100
    if missing_pitcher:
        confidence -= 25
    if away_form["games"] < 20 or home_form["games"] < 20:
        confidence -= 10
    if away_pitch is None or home_pitch is None:
        confidence -= 15
    confidence = max(35, min(confidence, 100))

    if best_edge >= 0.08 and confidence >= 75:
        verdict = "🔥 STRONG PLAY"
    elif best_edge >= 0.04 and confidence >= 65:
        verdict = "🟢 PLAY"
    elif best_edge >= 0.015:
        verdict = "🟡 LEAN"
    else:
        verdict = "⚪ PASS"

    st.divider()
    st.subheader(f"⏱️ F5 ANALYSIS: {game['away_abbr']} @ {game['home_abbr']}")

    p1, p2, p3 = st.columns(3)
    p1.metric(game["away_abbr"], f"{away_proj:.2f}")
    p2.metric(game["home_abbr"], f"{home_proj:.2f}")
    p3.metric("Total F5", f"{total_proj:.2f}")

    st.markdown("### 🧠 Probabilidades")
    st.write(f"**Under {f5_line}:** {probs['under']*100:.1f}%")
    st.write(f"**Over {f5_line}:** {probs['over']*100:.1f}%")
    if probs["push"] > 0:
        st.write(f"**Push:** {probs['push']*100:.1f}%")

    st.write(f"**{game['away_abbr']} gana F5:** {ml['away']*100:.1f}%")
    st.write(f"**{game['home_abbr']} gana F5:** {ml['home']*100:.1f}%")
    st.write(f"**Empate F5:** {ml['tie']*100:.1f}%")

    st.markdown("### 🎯 Valor contra mercado")
    st.write(
        f"Under {f5_line}: mercado {implied_under*100:.1f}% | "
        f"modelo {probs['under']*100:.1f}% | **edge {edge_under*100:+.1f} pp**"
    )
    st.write(
        f"Over {f5_line}: mercado {implied_over*100:.1f}% | "
        f"modelo {probs['over']*100:.1f}% | **edge {edge_over*100:+.1f} pp**"
    )

    fair = prob_to_american(best_prob)

    st.markdown("### 🏁 Decisión")
    if verdict.startswith("🔥") or verdict.startswith("🟢"):
        st.success(f"{verdict}: F5 {best_side} {f5_line}")
    elif verdict.startswith("🟡"):
        st.warning(f"{verdict}: F5 {best_side} {f5_line}")
    else:
        st.info("⚪ PASS — No hay ventaja suficiente para apostar.")

    st.write(f"**Fair odds del lado con mayor valor:** {fair}")
    st.write(f"**Confianza de datos:** {confidence}/100")

    with st.expander("🔬 Cómo calculó la proyección"):
        st.write(
            "Esta V2 mezcla ofensiva de temporada y últimos 15 juegos, "
            "y ajusta por ERA/WHIP del pitcher rival. Después usa una "
            "distribución Poisson para estimar probabilidades."
        )
        st.json({
            game["away_abbr"]: away_parts,
            game["home_abbr"]: home_parts,
        })

st.divider()
st.caption(
    "V2 experimental. Aún no incluye lineups confirmados, Statcast, parque, clima, "
    "umpire ni bullpen. No garantiza resultados ni ganancias."
)
