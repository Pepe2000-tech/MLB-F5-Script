from datetime import date, datetime
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from data_mlb import (
    get_schedule, get_team_form, get_pitcher_stats, get_weather,
    get_stadium_context, get_lineups, enrich_lineup,
    get_team_pitching_profile
)
from model import (
    project_f5_runs, project_full_game_runs_v4,
    total_probabilities, moneyline_probabilities,
    prob_to_decimal, min_target_odds,
    build_prop_candidates, rank_automatic_candidates,
    evaluate_selected_candidate, central_run_range
)

st.set_page_config(page_title="MLB Betting Hub V4.1", page_icon="⚾", layout="wide")
st_autorefresh(interval=120000, key="v41_refresh")

st.title("⚾ MLB Betting Hub — V4.1")
st.caption("Automático primero: te dice qué buscar. Después tú capturas el momio.")

# =========================
# Selección mínima
# =========================
c1, c2 = st.columns([1,2])
with c1:
    selected_date = st.date_input("📅 Fecha", value=date.today())

games = get_schedule(selected_date.isoformat())
if not games:
    st.warning("No encontré partidos MLB para esta fecha o MLB no respondió.")
    st.stop()

with c2:
    game_label = st.selectbox("⚾ Partido", [g["label"] for g in games])

game = next(g for g in games if g["label"] == game_label)

# =========================
# Datos automáticos
# =========================
with st.spinner("Analizando partido automáticamente..."):
    away_form = get_team_form(game["away_id"], selected_date.isoformat())
    home_form = get_team_form(game["home_id"], selected_date.isoformat())

    away_pitch = get_pitcher_stats(game["away_pitcher_id"], selected_date.year) if game["away_pitcher_id"] else None
    home_pitch = get_pitcher_stats(game["home_pitcher_id"], selected_date.year) if game["home_pitcher_id"] else None

    away_staff = get_team_pitching_profile(game["away_id"], selected_date.year, selected_date.isoformat())
    home_staff = get_team_pitching_profile(game["home_id"], selected_date.year, selected_date.isoformat())

    park = get_stadium_context(game["home_abbr"])
    weather = get_weather(
        park["lat"], park["lon"], selected_date.isoformat(), game.get("game_time_local")
    ) if park else None

    raw_lineups = get_lineups(game["game_pk"])
    away_lineup = enrich_lineup(
        raw_lineups.get("away", []), selected_date.year, (home_pitch or {}).get("hand", "R")
    )
    home_lineup = enrich_lineup(
        raw_lineups.get("home", []), selected_date.year, (away_pitch or {}).get("hand", "R")
    )

away_confirmed = len(away_lineup) >= 9
home_confirmed = len(home_lineup) >= 9
both_confirmed = away_confirmed and home_confirmed

# calidad
quality = 100
quality_notes = []
if not game["away_pitcher_id"] or not game["home_pitcher_id"]:
    quality -= 18
    quality_notes.append("⚠️ Falta al menos un abridor confirmado")
else:
    quality_notes.append("✅ Abridores confirmados")
if not away_confirmed:
    quality -= 12
    quality_notes.append(f"⚠️ Lineup {game['away_abbr']} pendiente")
else:
    quality_notes.append(f"✅ Lineup {game['away_abbr']} confirmado")
if not home_confirmed:
    quality -= 12
    quality_notes.append(f"⚠️ Lineup {game['home_abbr']} pendiente")
else:
    quality_notes.append(f"✅ Lineup {game['home_abbr']} confirmado")
if weather is None:
    quality -= 8
    quality_notes.append("⚠️ Clima no disponible")
else:
    quality_notes.append("✅ Clima disponible")
if away_staff is None or home_staff is None:
    quality -= 8
    quality_notes.append("⚠️ Bullpen proxy incompleto")
else:
    quality_notes.append("✅ Bullpen proxy disponible")

quality = max(30, min(100, quality))
park_factor = (park or {}).get("factor", 1.0)

away_f5, away_f5_debug = project_f5_runs(
    away_form, home_pitch, away_lineup, away_confirmed, park_factor, weather
)
home_f5, home_f5_debug = project_f5_runs(
    home_form, away_pitch, home_lineup, home_confirmed, park_factor, weather
)
f5_total = away_f5 + home_f5

away_fg, home_fg, fg_debug = project_full_game_runs_v4(
    away_f5, home_f5, away_form, home_form,
    away_staff, home_staff, park_factor, weather
)
fg_total = away_fg + home_fg

props = build_prop_candidates(
    away_pitcher=away_pitch,
    home_pitcher=home_pitch,
    away_pitcher_name=game["away_pitcher_name"],
    home_pitcher_name=game["home_pitcher_name"],
    away_lineup=away_lineup,
    home_lineup=home_lineup,
    away_team=game["away_abbr"],
    home_team=game["home_abbr"],
    lineups_confirmed=both_confirmed,
)

# =========================
# Construir candidatos automáticos sin momio
# =========================
automatic = []

# F5 totals estándar
for line in [3.5, 4.5, 5.5, 6.5]:
    pr = total_probabilities(f5_total, line)
    automatic += [
        {
            "category":"F5",
            "label":f"F5 Over {line:g}",
            "prob":pr["over"],
            "quality":quality,
            "confirmed":both_confirmed,
            "volatility":"medium",
            "reason":f"Total F5 proyectado {f5_total:.2f} vs línea {line:g}."
        },
        {
            "category":"F5",
            "label":f"F5 Under {line:g}",
            "prob":pr["under"],
            "quality":quality,
            "confirmed":both_confirmed,
            "volatility":"medium",
            "reason":f"Total F5 proyectado {f5_total:.2f} vs línea {line:g}."
        },
    ]

# F5 ML
f5_ml = moneyline_probabilities(away_f5, home_f5)
nt = f5_ml["away"] + f5_ml["home"]
pa = f5_ml["away"]/nt if nt else .5
ph = f5_ml["home"]/nt if nt else .5
automatic += [
    {
        "category":"F5",
        "label":f"{game['away_abbr']} F5 ML",
        "prob":pa,
        "quality":quality,
        "confirmed":both_confirmed,
        "volatility":"medium",
        "reason":f"Proyección F5 {game['away_abbr']} {away_f5:.2f} - {game['home_abbr']} {home_f5:.2f}."
    },
    {
        "category":"F5",
        "label":f"{game['home_abbr']} F5 ML",
        "prob":ph,
        "quality":quality,
        "confirmed":both_confirmed,
        "volatility":"medium",
        "reason":f"Proyección F5 {game['away_abbr']} {away_f5:.2f} - {game['home_abbr']} {home_f5:.2f}."
    },
]

# Full game total líneas estándar
for line in [7.5, 8.5, 9.5, 10.5]:
    pr = total_probabilities(fg_total, line)
    automatic += [
        {
            "category":"Full Game BETA",
            "label":f"Full Game Over {line:g}",
            "prob":pr["over"],
            "quality":max(35, quality-12),
            "confirmed":False,
            "volatility":"medium",
            "reason":f"Total juego proyectado {fg_total:.2f} vs línea {line:g}. Bullpen aún en modo BETA."
        },
        {
            "category":"Full Game BETA",
            "label":f"Full Game Under {line:g}",
            "prob":pr["under"],
            "quality":max(35, quality-12),
            "confirmed":False,
            "volatility":"medium",
            "reason":f"Total juego proyectado {fg_total:.2f} vs línea {line:g}. Bullpen aún en modo BETA."
        },
    ]

# Full game ML
fg_ml = moneyline_probabilities(away_fg, home_fg)
nt2 = fg_ml["away"] + fg_ml["home"]
fga = fg_ml["away"]/nt2 if nt2 else .5
fgh = fg_ml["home"]/nt2 if nt2 else .5
automatic += [
    {
        "category":"Full Game BETA",
        "label":f"{game['away_abbr']} ML Full Game",
        "prob":fga,
        "quality":max(35, quality-12),
        "confirmed":False,
        "volatility":"medium",
        "reason":f"Proyección juego completo {game['away_abbr']} {away_fg:.2f} - {game['home_abbr']} {home_fg:.2f}."
    },
    {
        "category":"Full Game BETA",
        "label":f"{game['home_abbr']} ML Full Game",
        "prob":fgh,
        "quality":max(35, quality-12),
        "confirmed":False,
        "volatility":"medium",
        "reason":f"Proyección juego completo {game['away_abbr']} {away_fg:.2f} - {game['home_abbr']} {home_fg:.2f}."
    },
]

# Props
for p in props:
    automatic.append({
        "category": p["category"],
        "label": p["label"],
        "prob": p["prob"],
        "quality": p.get("data_quality", 65),
        "confirmed": p.get("confirmed", False),
        "volatility": "high" if p["category"]=="Home Run" else "medium",
        "reason": p["reason"]
    })

ranked_auto = rank_automatic_candidates(automatic, max_items=5)

# =========================
# 2 pantallas
# =========================
tab1, tab2 = st.tabs(["1️⃣ Qué buscar", "2️⃣ Evaluar momios"])

with tab1:
    st.subheader(f"🤖 Qué jugaría primero en {game['away_abbr']} @ {game['home_abbr']}")

    top_status = "✅ COMPLETO" if both_confirmed else "⚠️ PROVISIONAL"
    q1,q2,q3 = st.columns([1,1,1.3])
    q1.metric("Calidad de análisis", f"{quality}/100")
    q2.metric("Estado", top_status)
    q3.caption(f"🔄 Actualizado {datetime.now().strftime('%H:%M:%S')} • refresco automático ~2 min")

    if not both_confirmed:
        st.warning("Faltan uno o ambos lineups. Las recomendaciones se recalcularán automáticamente cuando MLB los publique.")

    if not ranked_auto:
        st.info("⚪ No encontré una opción suficientemente interesante con los datos actuales.")
    else:
        st.markdown("### 🏆 TOP oportunidades para buscar en Draftea")
        for i, item in enumerate(ranked_auto, 1):
            icon = "🟢" if item["auto_grade"]=="ALTA" else "🟡" if item["auto_grade"]=="MEDIA" else "⚪"
            state = "CONFIRMADO" if item["confirmed"] else "PROVISIONAL"
            st.markdown(
                f"**{i}. {icon} {item['label']}**  \n"
                f"Modelo: **{item['prob']*100:.1f}%** · "
                f"Cuota justa: **{prob_to_decimal(item['prob']):.2f}x** · "
                f"🎯 Buscar **≥ {min_target_odds(item['prob']):.2f}x** · "
                f"{state}"
            )
            st.caption(item["reason"])

    with st.expander("🔬 Ver por qué recomienda esto", expanded=False):
        a,b,c = st.columns(3)
        a.metric(f"{game['away_abbr']} F5", f"{away_f5:.2f}")
        b.metric(f"{game['home_abbr']} F5", f"{home_f5:.2f}")
        c.metric("Total F5", f"{f5_total:.2f}")

        lo, hi = central_run_range(fg_total,.20,.80)
        a,b,c = st.columns(3)
        a.metric(f"{game['away_abbr']} Full", f"{away_fg:.2f}")
        b.metric(f"{game['home_abbr']} Full", f"{home_fg:.2f}")
        c.metric("Rango total", f"{lo}–{hi}")

        st.markdown("**Datos disponibles**")
        for note in quality_notes:
            st.write(note)

        st.markdown("**Contexto**")
        st.write(f"Parque: {(park or {}).get('name','N/D')} | factor {(park or {}).get('factor',1.0):.2f}")
        if weather:
            st.write(
                f"Clima: {weather['temp_f']:.0f}°F | viento {weather['wind_mph']:.0f} mph | "
                f"humedad {weather['humidity']:.0f}%"
            )

        st.markdown("**Lineups**")
        c1,c2 = st.columns(2)
        with c1:
            st.write(f"{game['away_abbr']} {'✅' if away_confirmed else '⚠️'}")
            for p in away_lineup[:9]:
                st.caption(f"{p['order']}. {p['name']} | OPS {p['ops']:.3f}")
        with c2:
            st.write(f"{game['home_abbr']} {'✅' if home_confirmed else '⚠️'}")
            for p in home_lineup[:9]:
                st.caption(f"{p['order']}. {p['name']} | OPS {p['ops']:.3f}")

with tab2:
    st.subheader("💰 ¿Draftea paga suficiente?")
    st.caption("Escoge solamente de las recomendaciones automáticas y captura el momio decimal que ves.")

    if not ranked_auto:
        st.info("Primero necesitamos al menos una recomendación automática.")
    else:
        labels = [x["label"] for x in ranked_auto]
        selected = st.multiselect(
            "¿Cuáles encontraste en Draftea?",
            labels,
            default=labels[:min(3, len(labels))]
        )

        evaluated = []
        for idx, label in enumerate(selected):
            item = next(x for x in ranked_auto if x["label"] == label)
            c1,c2,c3 = st.columns([2.2,1,1.1])
            c1.write(f"**{label}**")
            c2.caption(f"Necesitamos ≥ {min_target_odds(item['prob']):.2f}x")
            odds = c3.number_input(
                f"Momio {idx+1}",
                min_value=1.01,
                max_value=100.0,
                value=1.80,
                step=.01,
                format="%.2f",
                key=f"odd_v41_{idx}"
            )
            result = evaluate_selected_candidate(item, odds)
            evaluated.append({**item, **result, "odds":odds})

        if selected:
            evaluated = sorted(evaluated, key=lambda x: x["score"], reverse=True)
            st.markdown("### Resultado")
            best = evaluated[0]

            if best["verdict"] == "APOSTAR":
                st.success(f"🟢 MEJOR OPCIÓN: {best['label']} @ {best['odds']:.2f}x")
            elif best["verdict"] == "LEAN":
                st.warning(f"🟡 MEJOR OPCIÓN: {best['label']} @ {best['odds']:.2f}x")
            else:
                st.info("⚪ PASS GENERAL — Ninguno de los momios capturados compensa suficientemente el riesgo.")

            for i, x in enumerate(evaluated,1):
                icon = "🟢" if x["verdict"]=="APOSTAR" else "🟡" if x["verdict"]=="LEAN" else "⚪"
                st.write(
                    f"**{i}. {icon} {x['label']} @ {x['odds']:.2f}x** — "
                    f"Modelo {x['prob']*100:.1f}% | Cuota justa {x['fair_odds']:.2f}x | "
                    f"EV {x['ev']*100:+.1f}% | {x['verdict']}"
                )
        else:
            st.info("Selecciona al menos una recomendación que hayas encontrado en Draftea.")

st.divider()
st.caption(
    "V4.1 experimental. El Top 5 se genera sin conocer el momio; el momio se evalúa después. "
    "Full Game y props siguen en desarrollo y nunca deben interpretarse como garantía."
)
