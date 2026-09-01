from datetime import date, datetime
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from data_mlb import (
    get_schedule,
    get_team_form,
    get_pitcher_stats,
    get_weather,
    get_stadium_context,
    get_lineups,
    enrich_lineup,
)
from model import (
    project_f5_runs_v31,
    total_probabilities,
    moneyline_probabilities,
    no_vig_probs,
    expected_value_decimal,
    prob_to_decimal,
    grade_pick,
)

st.set_page_config(page_title="MLB F5 Model V3.1", page_icon="⚾", layout="centered")

# Refresca la app cada 2 minutos. Los widgets conservan su estado.
st_autorefresh(interval=120000, key="f5_lineup_refresh")

st.title("⚾ MLB F5 Model — V3.1")
st.caption("Primeras 5 entradas • Lineups automáticos • Matchup vs mano del abridor • Parque + clima")

selected_date = st.date_input("📅 Fecha", value=date.today())
games = get_schedule(selected_date.isoformat())

if not games:
    st.warning("No encontré partidos MLB para esta fecha o la fuente no respondió.")
    st.stop()

game_label = st.selectbox("⚾ Partido", [g["label"] for g in games])
game = next(g for g in games if g["label"] == game_label)

with st.spinner("Actualizando datos MLB, lineups y contexto..."):
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

    raw_lineups = get_lineups(game["game_pk"])

    away_lineup = enrich_lineup(
        raw_lineups.get("away", []),
        selected_date.year,
        (home_pitch or {}).get("hand", "R")
    )
    home_lineup = enrich_lineup(
        raw_lineups.get("home", []),
        selected_date.year,
        (away_pitch or {}).get("hand", "R")
    )

away_confirmed = len(away_lineup) >= 9
home_confirmed = len(home_lineup) >= 9
both_lineups_confirmed = away_confirmed and home_confirmed

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader(f"✈️ {game['away_abbr']}")
    st.write(f"**Pitcher:** {game['away_pitcher_name']}")
    if away_pitch:
        st.caption(
            f"{away_pitch['hand']}HP | ERA {away_pitch['era']:.2f} | WHIP {away_pitch['whip']:.2f} | "
            f"K/9 {away_pitch['k9']:.2f} | BB/9 {away_pitch['bb9']:.2f} | HR/9 {away_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {away_form['season_rpg']:.2f} | Últimos 15 {away_form['recent_rpg']:.2f}")

with c2:
    st.subheader(f"🏠 {game['home_abbr']}")
    st.write(f"**Pitcher:** {game['home_pitcher_name']}")
    if home_pitch:
        st.caption(
            f"{home_pitch['hand']}HP | ERA {home_pitch['era']:.2f} | WHIP {home_pitch['whip']:.2f} | "
            f"K/9 {home_pitch['k9']:.2f} | BB/9 {home_pitch['bb9']:.2f} | HR/9 {home_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {home_form['season_rpg']:.2f} | Últimos 15 {home_form['recent_rpg']:.2f}")

st.subheader("👥 Lineups automáticos")
lc1, lc2 = st.columns(2)

def render_lineup(title, lineup, confirmed, opp_hand):
    st.markdown(f"**{title}**")
    if confirmed:
        st.success(f"🟢 CONFIRMADO — {len(lineup)}/9")
    elif lineup:
        st.warning(f"🟡 PARCIAL — {len(lineup)}/9")
    else:
        st.info("⚪ NO DISPONIBLE TODAVÍA")

    if lineup:
        for p in lineup[:9]:
            split_txt = f"OPS vs {opp_hand}HP {p['ops']:.3f}"
            src = "split" if p["used_split"] else "temporada"
            st.write(f"{p['order']}. **{p['name']}** — {split_txt} ({src})")
    else:
        st.caption("MLB aún no publica la alineación. La proyección será provisional.")

with lc1:
    render_lineup(
        game["away_abbr"],
        away_lineup,
        away_confirmed,
        (home_pitch or {}).get("hand", "R")
    )
with lc2:
    render_lineup(
        game["home_abbr"],
        home_lineup,
        home_confirmed,
        (away_pitch or {}).get("hand", "R")
    )

if both_lineups_confirmed:
    st.success("✅ Ambos lineups confirmados. El modelo ya los incorpora.")
else:
    st.warning(
        "⚠️ Al menos un lineup no está confirmado. El modelo se actualizará automáticamente "
        "cada ~2 minutos y no permitirá marcar un STRONG PLAY mientras falte información."
    )

st.caption(f"Última actualización de pantalla: {datetime.now().strftime('%H:%M:%S')}")

st.subheader("🏟️ Contexto automático")
cc1, cc2, cc3 = st.columns(3)
cc1.metric("Park factor", f"{park['factor']:.2f}" if park else "N/D")
cc2.metric("Temperatura", f"{weather['temp_f']:.0f}°F" if weather else "N/D")
cc3.metric("Viento", f"{weather['wind_mph']:.0f} mph" if weather else "N/D")

away_proj, away_debug = project_f5_runs_v31(
    offense=away_form,
    opposing_pitcher=home_pitch,
    lineup=away_lineup,
    lineup_confirmed=away_confirmed,
    park_factor=park["factor"] if park else 1.0,
    weather=weather,
)

home_proj, home_debug = project_f5_runs_v31(
    offense=home_form,
    opposing_pitcher=away_pitch,
    lineup=home_lineup,
    lineup_confirmed=home_confirmed,
    park_factor=park["factor"] if park else 1.0,
    weather=weather,
)

total_proj = away_proj + home_proj
ml_probs = moneyline_probabilities(away_proj, home_proj)

st.divider()
st.subheader("🎰 Mercados F5")
st.caption("Cuotas decimales. Captura solamente los mercados que Draftea tenga disponibles.")

with st.expander("⚾ Money Line F5", expanded=True):
    a,b = st.columns(2)
    with a:
        away_ml = st.number_input(f"{game['away_abbr']} ML", 1.01, 20.0, 1.80, .01, format="%.2f")
    with b:
        home_ml = st.number_input(f"{game['home_abbr']} ML", 1.01, 20.0, 2.00, .01, format="%.2f")

with st.expander("📊 Total F5 — Línea 1", expanded=True):
    a,b,c = st.columns(3)
    with a:
        line1 = st.number_input("Línea 1", 2.5, 8.5, 4.5, .5)
    with b:
        over1 = st.number_input("Over 1", 1.01, 20.0, 1.90, .01, format="%.2f")
    with c:
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

    no_tie = ml_probs["away"] + ml_probs["home"]
    p_away_ml = ml_probs["away"]/no_tie if no_tie else .5
    p_home_ml = ml_probs["home"]/no_tie if no_tie else .5

    nv_away, nv_home, _ = no_vig_probs(away_ml, home_ml)

    candidates += [
        {
            "market": f"{game['away_abbr']} F5 ML",
            "p": p_away_ml,
            "odds": away_ml,
            "edge": p_away_ml - nv_away,
            "ev": expected_value_decimal(p_away_ml, away_ml),
        },
        {
            "market": f"{game['home_abbr']} F5 ML",
            "p": p_home_ml,
            "odds": home_ml,
            "edge": p_home_ml - nv_home,
            "ev": expected_value_decimal(p_home_ml, home_ml),
        },
    ]

    def add_total(line, over_odds, under_odds):
        probs = total_probabilities(total_proj, line)
        nv_u, nv_o, _ = no_vig_probs(under_odds, over_odds)
        candidates.extend([
            {
                "market": f"F5 UNDER {line:g}",
                "p": probs["under"],
                "odds": under_odds,
                "edge": probs["under"] - nv_u,
                "ev": expected_value_decimal(probs["under"], under_odds),
            },
            {
                "market": f"F5 OVER {line:g}",
                "p": probs["over"],
                "odds": over_odds,
                "edge": probs["over"] - nv_o,
                "ev": expected_value_decimal(probs["over"], over_odds),
            },
        ])

    add_total(line1, over1, under1)
    if use2:
        add_total(line2, over2, under2)
    if use3:
        add_total(line3, over3, under3)

    data_quality = 100

    if not game["away_pitcher_id"] or not game["home_pitcher_id"]:
        data_quality -= 20
    if away_pitch is None or home_pitch is None:
        data_quality -= 15
    if weather is None:
        data_quality -= 8
    if park is None:
        data_quality -= 4

    # Lineup tiene mucho peso en la calidad de datos.
    if not away_confirmed:
        data_quality -= 12
    if not home_confirmed:
        data_quality -= 12

    # Cobertura estadística de lineup.
    lineup_players = away_lineup[:9] + home_lineup[:9]
    if lineup_players:
        coverage = sum(1 for p in lineup_players if p["stats_available"]) / len(lineup_players)
        if coverage < .80:
            data_quality -= 8

    data_quality = max(25, min(100, data_quality))

    ranked = sorted(candidates, key=lambda x: x["ev"], reverse=True)
    best = ranked[0]

    verdict, pick_conf = grade_pick(
        best["ev"],
        best["edge"],
        data_quality,
        lineups_confirmed=both_lineups_confirmed,
    )

    st.divider()
    st.subheader("🤖 Proyección F5 V3.1")
    p1,p2,p3 = st.columns(3)
    p1.metric(game["away_abbr"], f"{away_proj:.2f}")
    p2.metric(game["home_abbr"], f"{home_proj:.2f}")
    p3.metric("Total F5", f"{total_proj:.2f}")

    st.subheader("🏆 Ranking de mercados")
    for i, c in enumerate(ranked, 1):
        st.write(
            f"**{i}. {c['market']} @ {c['odds']:.2f}x** — "
            f"Modelo {c['p']*100:.1f}% | Edge {c['edge']*100:+.1f} pp | EV {c['ev']*100:+.1f}%"
        )

    st.subheader("🎯 Recomendación")

    if not both_lineups_confirmed:
        st.caption("🟡 Recomendación provisional: falta al menos un lineup oficial.")

    if verdict == "PASS":
        st.info("⚪ PASS — Ningún mercado supera los filtros actuales.")
    elif verdict == "LEAN":
        st.warning(f"🟡 LEAN: {best['market']} @ {best['odds']:.2f}x")
    elif verdict == "PLAY":
        st.success(f"🟢 PLAY: {best['market']} @ {best['odds']:.2f}x")
    else:
        st.success(f"🔥 STRONG PLAY: {best['market']} @ {best['odds']:.2f}x")

    st.write(f"**Cuota justa:** {prob_to_decimal(best['p']):.2f}x")
    st.write(f"**Calidad de datos:** {data_quality}/100")
    st.write(f"**Confianza del pick:** {pick_conf}")
    st.write(f"**Lineups:** {'Confirmados ✅' if both_lineups_confirmed else 'Pendientes ⚠️'}")

    with st.expander("🔬 Ver factores del modelo"):
        st.json({
            game["away_abbr"]: away_debug,
            game["home_abbr"]: home_debug,
            "park": park,
            "weather": weather,
        })

st.divider()
st.caption(
    "V3.1 experimental. El matchup de lineup usa OPS vs mano del pitcher cuando MLB devuelve "
    "muestra suficiente; de lo contrario usa OPS de temporada. Aún falta Statcast y backtesting."
)
