
import math
import streamlit as st

st.set_page_config(page_title="MLB F5 Model", page_icon="⚾", layout="centered")

st.title("⚾ MLB F5 Model — MVP")
st.caption("Versión inicial: captura manual + cálculo probabilístico básico. Luego agregaremos datos en vivo e IA.")

def american_to_implied(odds):
    if odds is None:
        return None
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)

def prob_to_american(p):
    if p <= 0 or p >= 1:
        return None
    if p >= 0.5:
        return round(-100 * p / (1-p))
    return round(100 * (1-p) / p)

def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def total_under_probability(lambda_total, line):
    # Para líneas .5: P(total <= floor(line))
    # Para líneas enteras, devuelve probabilidad de ganar excluyendo push.
    max_k = int(math.floor(line - 1e-9))
    return sum(poisson_pmf(k, lambda_total) for k in range(max_k + 1))

def home_away_win_probs(lambda_away, lambda_home, max_runs=15):
    away_win = 0.0
    home_win = 0.0
    tie = 0.0
    for a in range(max_runs + 1):
        pa = poisson_pmf(a, lambda_away)
        for h in range(max_runs + 1):
            ph = poisson_pmf(h, lambda_home)
            p = pa * ph
            if a > h:
                away_win += p
            elif h > a:
                home_win += p
            else:
                tie += p
    total = away_win + home_win + tie
    if total > 0:
        away_win /= total
        home_win /= total
        tie /= total
    return away_win, home_win, tie

with st.form("f5_form"):
    col1, col2 = st.columns(2)

    with col1:
        away_team = st.text_input("Visitante", "PHI")
        away_pitcher = st.text_input("Pitcher visitante", "Jesús Luzardo")
        away_proj = st.number_input("Carreras proyectadas visitante", min_value=0.0, max_value=10.0, value=1.5, step=0.1)

    with col2:
        home_team = st.text_input("Local", "ARI")
        home_pitcher = st.text_input("Pitcher local", "Eduardo Rodriguez")
        home_proj = st.number_input("Carreras proyectadas local", min_value=0.0, max_value=10.0, value=1.5, step=0.1)

    st.subheader("Sportsbook")
    c1, c2, c3 = st.columns(3)
    with c1:
        f5_line = st.number_input("Línea F5", min_value=0.5, max_value=15.0, value=4.5, step=0.5)
    with c2:
        under_odds = st.number_input("Momio Under", value=-110, step=5)
    with c3:
        over_odds = st.number_input("Momio Over", value=-110, step=5)

    submitted = st.form_submit_button("🚀 Analizar partido", use_container_width=True)

if submitted:
    total_proj = away_proj + home_proj
    p_under = total_under_probability(total_proj, f5_line)
    p_over = 1 - p_under

    implied_under = american_to_implied(under_odds)
    implied_over = american_to_implied(over_odds)

    edge_under = p_under - implied_under
    edge_over = p_over - implied_over

    away_win, home_win, tie = home_away_win_probs(away_proj, home_proj)

    st.divider()
    st.subheader(f"⏱️ F5 ANALYSIS: {away_team} @ {home_team}")

    st.write(f"✈️ **{away_team}** ({away_pitcher})")
    st.write(f"🏠 **{home_team}** ({home_pitcher})")

    st.markdown("### 🤖 Proyección")
    x1, x2, x3 = st.columns(3)
    x1.metric(away_team, f"{away_proj:.2f}")
    x2.metric(home_team, f"{home_proj:.2f}")
    x3.metric("Total F5", f"{total_proj:.2f}")

    st.markdown("### 📊 Probabilidades del modelo")
    st.write(f"**Under {f5_line}:** {p_under*100:.1f}%")
    st.write(f"**Over {f5_line}:** {p_over*100:.1f}%")
    st.write(f"**{away_team} gana F5:** {away_win*100:.1f}%")
    st.write(f"**{home_team} gana F5:** {home_win*100:.1f}%")
    st.write(f"**Empate F5:** {tie*100:.1f}%")

    st.markdown("### 🎰 Comparación contra mercado")
    st.write(f"Under {f5_line} — Mercado: {implied_under*100:.1f}% | Modelo: {p_under*100:.1f}% | **Edge: {edge_under*100:+.1f} pp**")
    st.write(f"Over {f5_line} — Mercado: {implied_over*100:.1f}% | Modelo: {p_over*100:.1f}% | **Edge: {edge_over*100:+.1f} pp**")

    best_side = "UNDER" if edge_under >= edge_over else "OVER"
    best_edge = max(edge_under, edge_over)
    best_prob = p_under if best_side == "UNDER" else p_over

    if best_edge >= 0.08:
        verdict = "🔥 STRONG PLAY"
    elif best_edge >= 0.04:
        verdict = "🟢 PLAY"
    elif best_edge >= 0.015:
        verdict = "🟡 LEAN"
    else:
        verdict = "⚪ PASS"

    fair_odds = prob_to_american(best_prob)

    st.markdown("### 🎯 Decisión")
    st.success(f"{verdict}: F5 {best_side} {f5_line}")
    st.write(f"**Edge estimado:** {best_edge*100:+.1f} pp")
    st.write(f"**Fair odds del modelo:** {fair_odds}")

    st.info("Esta V1 usa una distribución Poisson básica sobre las carreras proyectadas que tú introduces. La siguiente versión calculará esas proyecciones automáticamente con pitchers, ofensiva, splits, parque, clima y datos en vivo.")

st.divider()
st.caption("MVP educativo. No garantiza resultados ni ganancias.")
