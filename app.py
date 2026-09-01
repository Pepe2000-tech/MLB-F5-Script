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
    project_full_game_runs,
    total_probabilities,
    moneyline_probabilities,
    no_vig_probs,
    expected_value_decimal,
    prob_to_decimal,
    grade_pick,
    build_prop_candidates,
    evaluate_prop_odds,
)

st.set_page_config(page_title="MLB Betting Hub V3.2", page_icon="⚾", layout="wide")
st_autorefresh(interval=120000, key="hub_refresh")

st.title("⚾ MLB Betting Hub — V3.2")
st.caption("F5 + Juego completo (beta) + Props de jugadores • Datos automáticos • Momios decimales")

selected_date = st.date_input("📅 Fecha", value=date.today())
games = get_schedule(selected_date.isoformat())

if not games:
    st.warning("No encontré partidos MLB para esta fecha.")
    st.stop()

game_label = st.selectbox("⚾ Partido", [g["label"] for g in games])
game = next(g for g in games if g["label"] == game_label)

with st.spinner("Actualizando MLB, abridores, lineups, parque y clima..."):
    away_form = get_team_form(game["away_id"], selected_date.isoformat())
    home_form = get_team_form(game["home_id"], selected_date.isoformat())

    away_pitch = get_pitcher_stats(game["away_pitcher_id"], selected_date.year) if game["away_pitcher_id"] else None
    home_pitch = get_pitcher_stats(game["home_pitcher_id"], selected_date.year) if game["home_pitcher_id"] else None

    park = get_stadium_context(game["home_abbr"])
    weather = get_weather(
        park["lat"],
        park["lon"],
        selected_date.isoformat(),
        game.get("game_time_local"),
    ) if park else None

    raw_lineups = get_lineups(game["game_pk"])

    away_lineup = enrich_lineup(
        raw_lineups.get("away", []),
        selected_date.year,
        (home_pitch or {}).get("hand", "R"),
    )
    home_lineup = enrich_lineup(
        raw_lineups.get("home", []),
        selected_date.year,
        (away_pitch or {}).get("hand", "R"),
    )

away_confirmed = len(away_lineup) >= 9
home_confirmed = len(home_lineup) >= 9
both_lineups_confirmed = away_confirmed and home_confirmed

# -------------------- CABECERA DE DATOS --------------------
st.divider()
c1, c2, c3 = st.columns([1,1,1])

with c1:
    st.subheader(f"✈️ {game['away_abbr']}")
    st.write(f"**Pitcher:** {game['away_pitcher_name']}")
    if away_pitch:
        st.caption(
            f"{away_pitch['hand']}HP | ERA {away_pitch['era']:.2f} | WHIP {away_pitch['whip']:.2f} | "
            f"K/9 {away_pitch['k9']:.2f} | BB/9 {away_pitch['bb9']:.2f} | HR/9 {away_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {away_form['season_rpg']:.2f} | L15 {away_form['recent_rpg']:.2f}")

with c2:
    st.subheader(f"🏠 {game['home_abbr']}")
    st.write(f"**Pitcher:** {game['home_pitcher_name']}")
    if home_pitch:
        st.caption(
            f"{home_pitch['hand']}HP | ERA {home_pitch['era']:.2f} | WHIP {home_pitch['whip']:.2f} | "
            f"K/9 {home_pitch['k9']:.2f} | BB/9 {home_pitch['bb9']:.2f} | HR/9 {home_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {home_form['season_rpg']:.2f} | L15 {home_form['recent_rpg']:.2f}")

with c3:
    st.subheader("🏟️ Contexto")
    st.write(f"**Parque:** {(park or {}).get('name','N/D')}")
    st.caption(f"Park factor: {(park or {}).get('factor',1.0):.2f}")
    if weather:
        st.caption(
            f"{weather['temp_f']:.0f}°F | Viento {weather['wind_mph']:.0f} mph | "
            f"Humedad {weather['humidity']:.0f}%"
        )
    else:
        st.caption("Clima N/D")

st.caption(
    f"Lineups: {game['away_abbr']} {'✅' if away_confirmed else '⚠️'} | "
    f"{game['home_abbr']} {'✅' if home_confirmed else '⚠️'} • "
    f"Actualizado {datetime.now().strftime('%H:%M:%S')}"
)

away_f5, away_debug = project_f5_runs_v31(
    offense=away_form,
    opposing_pitcher=home_pitch,
    lineup=away_lineup,
    lineup_confirmed=away_confirmed,
    park_factor=(park or {}).get("factor",1.0),
    weather=weather,
)
home_f5, home_debug = project_f5_runs_v31(
    offense=home_form,
    opposing_pitcher=away_pitch,
    lineup=home_lineup,
    lineup_confirmed=home_confirmed,
    park_factor=(park or {}).get("factor",1.0),
    weather=weather,
)

tabs = st.tabs(["⏱️ Primeras 5", "🕘 Juego completo (BETA)", "👤 Props de jugadores"])

# ============================================================
# TAB 1: F5
# ============================================================
with tabs[0]:
    st.subheader("⏱️ Primeras 5 entradas")

    if not both_lineups_confirmed:
        st.warning("⚠️ Proyección provisional: falta al menos un lineup confirmado.")

    f5_total = away_f5 + home_f5
    ml_probs = moneyline_probabilities(away_f5, home_f5)

    m1,m2,m3 = st.columns(3)
    m1.metric(game["away_abbr"], f"{away_f5:.2f}")
    m2.metric(game["home_abbr"], f"{home_f5:.2f}")
    m3.metric("Total F5", f"{f5_total:.2f}")

    st.markdown("### 🎰 Mercados F5")
    a,b = st.columns(2)
    with a:
        away_ml = st.number_input(f"{game['away_abbr']} F5 ML", 1.01, 20.0, 1.80, .01, format="%.2f", key="f5aml")
    with b:
        home_ml = st.number_input(f"{game['home_abbr']} F5 ML", 1.01, 20.0, 2.00, .01, format="%.2f", key="f5hml")

    lines = []
    for idx, default_line in enumerate([4.5, 5.5, 6.5], start=1):
        use = True if idx == 1 else st.checkbox(f"Comparar línea F5 #{idx}", value=False, key=f"usef5{idx}")
        if use:
            c1,c2,c3 = st.columns(3)
            with c1:
                line = st.number_input(f"Línea F5 #{idx}", 2.5, 8.5, default_line, .5, key=f"f5line{idx}")
            with c2:
                over = st.number_input(f"Over #{idx}", 1.01, 20.0, 1.90 if idx==1 else 2.10, .01, format="%.2f", key=f"f5over{idx}")
            with c3:
                under = st.number_input(f"Under #{idx}", 1.01, 20.0, 1.90 if idx==1 else 1.75, .01, format="%.2f", key=f"f5under{idx}")
            lines.append((line,over,under))

    if st.button("🚀 Analizar mercados F5", use_container_width=True):
        candidates=[]

        no_tie = ml_probs["away"] + ml_probs["home"]
        p_a = ml_probs["away"]/no_tie if no_tie else .5
        p_h = ml_probs["home"]/no_tie if no_tie else .5
        nv_a,nv_h,_ = no_vig_probs(away_ml,home_ml)

        candidates += [
            {"market":f"{game['away_abbr']} F5 ML","p":p_a,"odds":away_ml,"edge":p_a-nv_a,"ev":expected_value_decimal(p_a,away_ml)},
            {"market":f"{game['home_abbr']} F5 ML","p":p_h,"odds":home_ml,"edge":p_h-nv_h,"ev":expected_value_decimal(p_h,home_ml)},
        ]

        for line,over,under in lines:
            probs=total_probabilities(f5_total,line)
            nv_u,nv_o,_=no_vig_probs(under,over)
            candidates += [
                {"market":f"F5 UNDER {line:g}","p":probs["under"],"odds":under,"edge":probs["under"]-nv_u,"ev":expected_value_decimal(probs["under"],under)},
                {"market":f"F5 OVER {line:g}","p":probs["over"],"odds":over,"edge":probs["over"]-nv_o,"ev":expected_value_decimal(probs["over"],over)},
            ]

        dq=100
        if not both_lineups_confirmed: dq-=24
        if away_pitch is None or home_pitch is None: dq-=15
        if weather is None: dq-=8
        ranked=sorted(candidates,key=lambda x:x["ev"],reverse=True)
        best=ranked[0]
        verdict,conf=grade_pick(best["ev"],best["edge"],dq,both_lineups_confirmed)

        st.markdown("### 🏆 Ranking")
        for i,c in enumerate(ranked,1):
            st.write(f"**{i}. {c['market']} @ {c['odds']:.2f}x** — Modelo {c['p']*100:.1f}% | Edge {c['edge']*100:+.1f} pp | EV {c['ev']*100:+.1f}%")

        st.markdown("### 🎯 Recomendación")
        if verdict=="PASS":
            st.info("⚪ PASS")
        elif verdict=="LEAN":
            st.warning(f"🟡 LEAN: {best['market']} @ {best['odds']:.2f}x")
        elif verdict=="PLAY":
            st.success(f"🟢 PLAY: {best['market']} @ {best['odds']:.2f}x")
        else:
            st.success(f"🔥 STRONG PLAY: {best['market']} @ {best['odds']:.2f}x")
        st.caption(f"Cuota justa {prob_to_decimal(best['p']):.2f}x | Calidad datos {dq}/100 | Confianza {conf}")

# ============================================================
# TAB 2: FULL GAME
# ============================================================
with tabs[1]:
    st.subheader("🕘 Juego completo — BETA")
    st.warning("⚠️ Este módulo todavía es BETA. Aún no modela bullpen en detalle; no permite STRONG PLAY.")

    away_fg, home_fg = project_full_game_runs(
        away_form, home_form, away_pitch, home_pitch,
        (park or {}).get("factor",1.0), weather
    )
    fg_total = away_fg + home_fg
    fg_ml = moneyline_probabilities(away_fg,home_fg)

    c1,c2,c3=st.columns(3)
    c1.metric(game["away_abbr"],f"{away_fg:.2f}")
    c2.metric(game["home_abbr"],f"{home_fg:.2f}")
    c3.metric("Total juego",f"{fg_total:.2f}")

    f1,f2=st.columns(2)
    with f1:
        fg_away_odds=st.number_input(f"{game['away_abbr']} ML Full Game",1.01,20.0,1.80,.01,format="%.2f",key="fgaml")
    with f2:
        fg_home_odds=st.number_input(f"{game['home_abbr']} ML Full Game",1.01,20.0,2.00,.01,format="%.2f",key="fghml")

    f1,f2,f3=st.columns(3)
    with f1:
        fg_line=st.number_input("Total Full Game",5.5,15.5,8.5,.5,key="fgline")
    with f2:
        fg_over=st.number_input("Over Full Game",1.01,20.0,1.90,.01,format="%.2f",key="fgover")
    with f3:
        fg_under=st.number_input("Under Full Game",1.01,20.0,1.90,.01,format="%.2f",key="fgunder")

    if st.button("🧪 Analizar Full Game BETA",use_container_width=True):
        probs=total_probabilities(fg_total,fg_line)
        nv_u,nv_o,_=no_vig_probs(fg_under,fg_over)

        no_tie=fg_ml["away"]+fg_ml["home"]
        p_a=fg_ml["away"]/no_tie if no_tie else .5
        p_h=fg_ml["home"]/no_tie if no_tie else .5
        nv_a,nv_h,_=no_vig_probs(fg_away_odds,fg_home_odds)

        candidates=[
            {"market":f"{game['away_abbr']} ML","p":p_a,"odds":fg_away_odds,"edge":p_a-nv_a,"ev":expected_value_decimal(p_a,fg_away_odds)},
            {"market":f"{game['home_abbr']} ML","p":p_h,"odds":fg_home_odds,"edge":p_h-nv_h,"ev":expected_value_decimal(p_h,fg_home_odds)},
            {"market":f"UNDER {fg_line:g}","p":probs["under"],"odds":fg_under,"edge":probs["under"]-nv_u,"ev":expected_value_decimal(probs["under"],fg_under)},
            {"market":f"OVER {fg_line:g}","p":probs["over"],"odds":fg_over,"edge":probs["over"]-nv_o,"ev":expected_value_decimal(probs["over"],fg_over)},
        ]
        ranked=sorted(candidates,key=lambda x:x["ev"],reverse=True)
        for i,c in enumerate(ranked,1):
            st.write(f"**{i}. {c['market']} @ {c['odds']:.2f}x** — Modelo {c['p']*100:.1f}% | EV {c['ev']*100:+.1f}%")
        if ranked[0]["ev"]>=.06:
            st.warning(f"🟡 LEAN BETA: {ranked[0]['market']} @ {ranked[0]['odds']:.2f}x")
        else:
            st.info("⚪ PASS BETA")

# ============================================================
# TAB 3: PLAYER PROPS
# ============================================================
with tabs[2]:
    st.subheader("👤 Props de jugadores")
    st.caption("El sistema propone candidatos primero; después tú introduces el momio de Draftea.")

    if not both_lineups_confirmed:
        st.warning("⚠️ Props de bateadores serán provisionales hasta que ambos lineups estén confirmados.")

    props = build_prop_candidates(
        away_pitcher=away_pitch,
        home_pitcher=home_pitch,
        away_pitcher_name=game["away_pitcher_name"],
        home_pitcher_name=game["home_pitcher_name"],
        away_lineup=away_lineup,
        home_lineup=home_lineup,
        away_team=game["away_abbr"],
        home_team=game["home_abbr"],
    )

    if not props:
        st.info("Todavía no hay suficientes datos para generar props.")
    else:
        market_filter = st.multiselect(
            "Mercados que quieres considerar",
            ["Pitcher Ks","Hits","Total Bases","HRR","Home Run"],
            default=["Pitcher Ks","Hits","Total Bases"],
        )

        filtered=[p for p in props if p["category"] in market_filter]
        filtered=sorted(filtered,key=lambda x:(x["safety"],x["prob"]),reverse=True)

        st.markdown("### 🔎 Recomendaciones automáticas (sin considerar momio)")
        for i,p in enumerate(filtered[:12],1):
            badge = "🟢" if p["safety"]>=75 else "🟡" if p["safety"]>=60 else "⚪"
            st.write(
                f"**{i}. {badge} {p['label']}** — "
                f"Prob. modelo {p['prob']*100:.1f}% | Seguridad {p['safety']}/100"
            )

        st.info("Estas son probabilidades del modelo, no apuestas todavía. Falta comparar contra el momio real.")

        options={p["label"]:p for p in filtered}
        if options:
            chosen_label=st.selectbox("🎯 Selecciona un prop para evaluar",list(options.keys()))
            chosen=options[chosen_label]
            odds=st.number_input("Momio decimal de Draftea",1.01,50.0,1.80,.01,format="%.2f",key="propodds")

            if st.button("💰 Evaluar este prop",use_container_width=True):
                result=evaluate_prop_odds(chosen,odds)

                c1,c2,c3,c4=st.columns(4)
                c1.metric("Modelo",f"{chosen['prob']*100:.1f}%")
                c2.metric("Cuota justa",f"{result['fair_odds']:.2f}x")
                c3.metric("EV",f"{result['ev']*100:+.1f}%")
                c4.metric("Seguridad",f"{chosen['safety']}/100")

                st.markdown("### 🎯 Decisión del prop")
                if result["verdict"]=="PASS":
                    st.info("⚪ PASS — El momio no compensa el riesgo.")
                elif result["verdict"]=="LEAN":
                    st.warning(f"🟡 LEAN: {chosen['label']} @ {odds:.2f}x")
                elif result["verdict"]=="PLAY":
                    st.success(f"🟢 PLAY: {chosen['label']} @ {odds:.2f}x")
                else:
                    st.success(f"🔥 STRONG PLAY: {chosen['label']} @ {odds:.2f}x")

                st.caption(chosen["reason"])

st.divider()
st.caption(
    "V3.2 experimental. F5 es el módulo más desarrollado. Full Game y Player Props son BETA. "
    "Aún falta Statcast, bullpen avanzado y backtesting/calibración."
)
