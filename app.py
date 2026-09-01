from datetime import date
import streamlit as st
from data_mlb import get_schedule, get_team_form, get_pitcher_stats
from model import (
    project_f5_runs, total_probabilities, moneyline_probabilities,
    no_vig_probs, expected_value_decimal, prob_to_decimal
)

st.set_page_config(page_title="MLB F5 Model V2.2", page_icon="⚾", layout="centered")
st.title("⚾ MLB F5 Model — V2.2")
st.caption("Exclusivo Primeras 5 Entradas • Datos MLB automáticos • Mercados Draftea")

day = st.date_input("📅 Fecha", value=date.today())
games = get_schedule(day.isoformat())
if not games:
    st.warning("No encontré juegos MLB para esta fecha.")
    st.stop()

label = st.selectbox("⚾ Partido", [g["label"] for g in games])
g = next(x for x in games if x["label"] == label)

with st.spinner("Consultando MLB..."):
    af = get_team_form(g["away_id"], day.isoformat())
    hf = get_team_form(g["home_id"], day.isoformat())
    ap = get_pitcher_stats(g["away_pitcher_id"], day.year) if g["away_pitcher_id"] else None
    hp = get_pitcher_stats(g["home_pitcher_id"], day.year) if g["home_pitcher_id"] else None

c1,c2=st.columns(2)
with c1:
    st.subheader(f"✈️ {g['away_abbr']}")
    st.write(g["away_pitcher_name"])
    st.caption(f"RPG {af['season_rpg']:.2f} | L15 {af['recent_rpg']:.2f}")
    if ap: st.caption(f"ERA {ap['era']:.2f} | WHIP {ap['whip']:.2f}")
with c2:
    st.subheader(f"🏠 {g['home_abbr']}")
    st.write(g["home_pitcher_name"])
    st.caption(f"RPG {hf['season_rpg']:.2f} | L15 {hf['recent_rpg']:.2f}")
    if hp: st.caption(f"ERA {hp['era']:.2f} | WHIP {hp['whip']:.2f}")

away_proj, _ = project_f5_runs(af, hp, bool(g["home_pitcher_id"]))
home_proj, _ = project_f5_runs(hf, ap, bool(g["away_pitcher_id"]))
total_proj = away_proj + home_proj
ml = moneyline_probabilities(away_proj, home_proj)

st.divider()
st.subheader("🎰 Cuotas F5 de Draftea")
st.caption("Escribe únicamente los mercados que quieras comparar. Cuotas en decimal.")

with st.expander("⚾ Money Line F5", expanded=True):
    a_ml = st.number_input(f"{g['away_abbr']} ML", 1.01, 20.0, 1.82, .01, format="%.2f")
    h_ml = st.number_input(f"{g['home_abbr']} ML", 1.01, 20.0, 2.00, .01, format="%.2f")

with st.expander("📊 Total F5 — Línea principal", expanded=True):
    line1 = st.number_input("Línea principal", 2.5, 7.5, 4.5, .5)
    o1 = st.number_input("Over línea principal", 1.01, 20.0, 1.90, .01, format="%.2f")
    u1 = st.number_input("Under línea principal", 1.01, 20.0, 1.90, .01, format="%.2f")

with st.expander("📊 Total F5 — Segunda línea (opcional)", expanded=False):
    use2 = st.checkbox("Comparar segunda línea")
    line2 = st.number_input("Segunda línea", 2.5, 8.5, 5.5, .5)
    o2 = st.number_input("Over segunda línea", 1.01, 20.0, 2.10, .01, format="%.2f")
    u2 = st.number_input("Under segunda línea", 1.01, 20.0, 1.74, .01, format="%.2f")

if st.button("🚀 Buscar mejor apuesta F5", use_container_width=True):
    candidates=[]

    # ML is modeled as 2-way "draw no action"-style comparison by conditioning on no tie.
    no_tie = ml["away"] + ml["home"]
    p_a_ml = ml["away"]/no_tie if no_tie else .5
    p_h_ml = ml["home"]/no_tie if no_tie else .5
    nv_a,nv_h,_ = no_vig_probs(a_ml,h_ml)
    candidates += [
        {"market":f"{g['away_abbr']} F5 ML","p":p_a_ml,"odds":a_ml,"edge":p_a_ml-nv_a,"ev":expected_value_decimal(p_a_ml,a_ml)},
        {"market":f"{g['home_abbr']} F5 ML","p":p_h_ml,"odds":h_ml,"edge":p_h_ml-nv_h,"ev":expected_value_decimal(p_h_ml,h_ml)}
    ]

    def add_total(line, over_odds, under_odds):
        probs=total_probabilities(total_proj,line)
        nv_u,nv_o,_=no_vig_probs(under_odds,over_odds)
        candidates.extend([
            {"market":f"F5 UNDER {line:g}","p":probs["under"],"odds":under_odds,"edge":probs["under"]-nv_u,"ev":expected_value_decimal(probs["under"],under_odds)},
            {"market":f"F5 OVER {line:g}","p":probs["over"],"odds":over_odds,"edge":probs["over"]-nv_o,"ev":expected_value_decimal(probs["over"],over_odds)}
        ])
    add_total(line1,o1,u1)
    if use2: add_total(line2,o2,u2)

    best=max(candidates,key=lambda x:x["ev"])

    confidence=100
    if not g["away_pitcher_id"] or not g["home_pitcher_id"]: confidence-=25
    if ap is None or hp is None: confidence-=15

    if best["ev"]>=.12 and best["edge"]>=.06 and confidence>=80: verdict="🔥 STRONG PLAY"
    elif best["ev"]>=.06 and best["edge"]>=.035 and confidence>=70: verdict="🟢 PLAY"
    elif best["ev"]>=.02 and best["edge"]>=.015 and confidence>=60: verdict="🟡 LEAN"
    else: verdict="⚪ PASS"

    st.divider()
    st.subheader("🤖 Proyección F5")
    x,y,z=st.columns(3)
    x.metric(g["away_abbr"],f"{away_proj:.2f}")
    y.metric(g["home_abbr"],f"{home_proj:.2f}")
    z.metric("Total",f"{total_proj:.2f}")

    st.subheader("🏆 Ranking de mercados")
    for i,c in enumerate(sorted(candidates,key=lambda x:x["ev"],reverse=True),1):
        st.write(f"**{i}. {c['market']} @ {c['odds']:.2f}x** — Modelo {c['p']*100:.1f}% | Edge {c['edge']*100:+.1f} pp | EV {c['ev']*100:+.1f}%")

    st.subheader("🎯 Recomendación")
    if verdict=="⚪ PASS":
        st.info("⚪ PASS — Ninguno de los mercados capturados supera nuestros filtros.")
    elif verdict.startswith("🟡"):
        st.warning(f"{verdict}: {best['market']} @ {best['odds']:.2f}x")
    else:
        st.success(f"{verdict}: {best['market']} @ {best['odds']:.2f}x")
    st.write(f"Cuota justa estimada: **{prob_to_decimal(best['p']):.2f}x**")
    st.write(f"Confianza de datos: **{confidence}/100**")
    st.caption("La V2.2 compara valor; no obliga a producir una apuesta.")

st.divider()
st.caption("Modelo experimental F5. V3 añadirá splits R/L, Statcast, lineups, parque/clima y backtesting.")
