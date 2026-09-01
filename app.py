from datetime import date, datetime
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from data_mlb import (
    get_schedule, get_team_form, get_pitcher_stats, get_weather,
    get_stadium_context, get_lineups, enrich_lineup,
    get_team_pitching_profile,
)
from model import (
    project_f5_runs, project_full_game_runs_v4,
    total_probabilities, moneyline_probabilities, no_vig_probs,
    expected_value_decimal, prob_to_decimal, grade_market,
    build_prop_candidates, evaluate_prop_odds, min_target_odds,
    central_run_range,
)

st.set_page_config(page_title="MLB Betting Hub V4", page_icon="⚾", layout="wide")
st_autorefresh(interval=120000, key="v4_refresh")

st.title("⚾ MLB Betting Hub — V4")
st.caption("🏆 Mejor apuesta del partido • F5 • Juego completo • Props • Datos automáticos")

# -------------------------
# Partido y datos automáticos
# -------------------------
selected_date = st.date_input("📅 Fecha", value=date.today())
games = get_schedule(selected_date.isoformat())
if not games:
    st.warning("No encontré partidos MLB para esta fecha o MLB no respondió.")
    st.stop()

game_label = st.selectbox("⚾ Escoge el juego", [g["label"] for g in games])
game = next(g for g in games if g["label"] == game_label)

with st.spinner("Actualizando MLB, abridores, lineups, bullpen proxy, parque y clima..."):
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
both_lineups_confirmed = away_confirmed and home_confirmed

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

# Calidad global
data_quality = 100
quality_notes = []
if not game["away_pitcher_id"] or not game["home_pitcher_id"]:
    data_quality -= 18; quality_notes.append("⚠️ Falta al menos un abridor confirmado")
else:
    quality_notes.append("✅ Abridores confirmados")
if not away_confirmed:
    data_quality -= 12; quality_notes.append(f"⚠️ Lineup {game['away_abbr']} pendiente")
else:
    quality_notes.append(f"✅ Lineup {game['away_abbr']} confirmado")
if not home_confirmed:
    data_quality -= 12; quality_notes.append(f"⚠️ Lineup {game['home_abbr']} pendiente")
else:
    quality_notes.append(f"✅ Lineup {game['home_abbr']} confirmado")
if weather is None:
    data_quality -= 8; quality_notes.append("⚠️ Clima no disponible")
else:
    quality_notes.append("✅ Clima disponible")
if park is None:
    data_quality -= 4; quality_notes.append("⚠️ Parque no disponible")
else:
    quality_notes.append("✅ Parque identificado")
if away_staff is None or home_staff is None:
    data_quality -= 8; quality_notes.append("⚠️ Bullpen proxy incompleto")
else:
    quality_notes.append("✅ Bullpen proxy disponible")
data_quality = max(25, min(100, data_quality))

# Props disponibles
all_props = build_prop_candidates(
    away_pitcher=away_pitch,
    home_pitcher=home_pitch,
    away_pitcher_name=game["away_pitcher_name"],
    home_pitcher_name=game["home_pitcher_name"],
    away_lineup=away_lineup,
    home_lineup=home_lineup,
    away_team=game["away_abbr"],
    home_team=game["home_abbr"],
    lineups_confirmed=both_lineups_confirmed,
)

# -------------------------
# Cabecera
# -------------------------
st.divider()
h1,h2,h3 = st.columns([1,1,1.1])
with h1:
    st.subheader(f"✈️ {game['away_abbr']}")
    st.write(f"**Abridor:** {game['away_pitcher_name']}")
    if away_pitch:
        st.caption(
            f"{away_pitch['hand']}HP | ERA {away_pitch['era']:.2f} | WHIP {away_pitch['whip']:.2f} | "
            f"K/9 {away_pitch['k9']:.2f} | BB/9 {away_pitch['bb9']:.2f} | HR/9 {away_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {away_form['season_rpg']:.2f} | L15 {away_form['recent_rpg']:.2f}")

with h2:
    st.subheader(f"🏠 {game['home_abbr']}")
    st.write(f"**Abridor:** {game['home_pitcher_name']}")
    if home_pitch:
        st.caption(
            f"{home_pitch['hand']}HP | ERA {home_pitch['era']:.2f} | WHIP {home_pitch['whip']:.2f} | "
            f"K/9 {home_pitch['k9']:.2f} | BB/9 {home_pitch['bb9']:.2f} | HR/9 {home_pitch['hr9']:.2f}"
        )
    st.caption(f"RPG {home_form['season_rpg']:.2f} | L15 {home_form['recent_rpg']:.2f}")

with h3:
    st.subheader("🏟️ Contexto")
    st.write(f"**Parque:** {(park or {}).get('name','N/D')}")
    st.caption(f"Park factor {(park or {}).get('factor',1.0):.2f}")
    if weather:
        st.caption(
            f"{weather['temp_f']:.0f}°F | viento {weather['wind_mph']:.0f} mph | "
            f"humedad {weather['humidity']:.0f}%"
        )
    st.caption(
        f"Lineups: {game['away_abbr']} {'✅' if away_confirmed else '⚠️'} | "
        f"{game['home_abbr']} {'✅' if home_confirmed else '⚠️'}"
    )

st.caption(f"🔄 Última actualización: {datetime.now().strftime('%H:%M:%S')} • Calidad global de datos: {data_quality}/100")

# ============================================================
# Mercados capturados una sola vez
# ============================================================
st.subheader("🎰 Mercados de Draftea")
st.caption("Activa únicamente los mercados que realmente veas en Draftea. Las cuotas son decimales.")

with st.expander("⏱️ Primeras 5 — Capturar cuotas", expanded=True):
    use_f5_ml = st.checkbox("Incluir Money Line F5", value=True)
    f5a,f5h = st.columns(2)
    with f5a:
        f5_away_ml = st.number_input(f"{game['away_abbr']} F5 ML",1.01,50.0,1.80,.01,format="%.2f")
    with f5h:
        f5_home_ml = st.number_input(f"{game['home_abbr']} F5 ML",1.01,50.0,2.00,.01,format="%.2f")

    f5_lines=[]
    defaults=[(4.5,1.90,1.90),(5.5,2.10,1.75),(6.5,2.50,1.55)]
    for idx,(dl,do,du) in enumerate(defaults,1):
        use = st.checkbox(f"Incluir total F5 #{idx}", value=(idx==1), key=f"v4_usef5_{idx}")
        if use:
            a,b,c=st.columns(3)
            with a: line=st.number_input(f"Línea F5 #{idx}",2.5,9.5,dl,.5,key=f"v4_f5line_{idx}")
            with b: over=st.number_input(f"Over F5 #{idx}",1.01,50.0,do,.01,format="%.2f",key=f"v4_f5over_{idx}")
            with c: under=st.number_input(f"Under F5 #{idx}",1.01,50.0,du,.01,format="%.2f",key=f"v4_f5under_{idx}")
            f5_lines.append((line,over,under))

with st.expander("🕘 Juego completo — Capturar cuotas", expanded=False):
    use_fg_ml = st.checkbox("Incluir Money Line Full Game", value=True)
    a,b=st.columns(2)
    with a: fg_away_ml=st.number_input(f"{game['away_abbr']} ML Full Game",1.01,50.0,1.80,.01,format="%.2f")
    with b: fg_home_ml=st.number_input(f"{game['home_abbr']} ML Full Game",1.01,50.0,2.00,.01,format="%.2f")

    use_fg_total = st.checkbox("Incluir Total Full Game", value=True)
    a,b,c=st.columns(3)
    with a: fg_market_line=st.number_input("Línea Draftea Full Game",5.5,16.5,8.5,.5)
    with b: fg_over=st.number_input("Over Full Game",1.01,50.0,1.90,.01,format="%.2f")
    with c: fg_under=st.number_input("Under Full Game",1.01,50.0,1.90,.01,format="%.2f")

with st.expander("👤 Props — Seleccionar hasta 3 para comparar", expanded=False):
    if not all_props:
        st.info("Aún no hay props calculables.")
        selected_prop_labels=[]
        prop_odds={}
    else:
        safe_sorted=sorted(all_props,key=lambda p:(p["safety"],p["prob"]),reverse=True)
        labels=[p["label"] for p in safe_sorted]
        defaults_props=labels[:min(3,len(labels))]
        selected_prop_labels=st.multiselect(
            "Props que sí están disponibles en Draftea",
            labels,
            default=defaults_props
        )
        prop_odds={}
        for i,label in enumerate(selected_prop_labels):
            prop=next(p for p in all_props if p["label"]==label)
            c1,c2,c3=st.columns([2,1,1])
            c1.write(f"**{label}**")
            c2.caption(f"Cuota mínima objetivo: {min_target_odds(prop['prob']):.2f}x")
            prop_odds[label]=c3.number_input(
                f"Momio {i+1}",1.01,100.0,1.80,.01,format="%.2f",key=f"v4_propodd_{i}"
            )

# ============================================================
# Construcción de oportunidades para ranking global
# ============================================================
def build_market_candidates():
    markets=[]

    # F5 ML
    f5_ml_probs=moneyline_probabilities(away_f5,home_f5)
    no_tie=f5_ml_probs["away"]+f5_ml_probs["home"]
    p_a=f5_ml_probs["away"]/no_tie if no_tie else .5
    p_h=f5_ml_probs["home"]/no_tie if no_tie else .5
    if use_f5_ml:
        nv_a,nv_h,_=no_vig_probs(f5_away_ml,f5_home_ml)
        markets += [
            {"section":"F5","market":f"{game['away_abbr']} F5 ML","p":p_a,"odds":f5_away_ml,
             "edge":p_a-nv_a,"ev":expected_value_decimal(p_a,f5_away_ml),"dq":data_quality,
             "confirmed":both_lineups_confirmed},
            {"section":"F5","market":f"{game['home_abbr']} F5 ML","p":p_h,"odds":f5_home_ml,
             "edge":p_h-nv_h,"ev":expected_value_decimal(p_h,f5_home_ml),"dq":data_quality,
             "confirmed":both_lineups_confirmed},
        ]

    # F5 totals
    for line,over,under in f5_lines:
        probs=total_probabilities(f5_total,line)
        nv_u,nv_o,_=no_vig_probs(under,over)
        markets += [
            {"section":"F5","market":f"F5 UNDER {line:g}","p":probs["under"],"odds":under,
             "edge":probs["under"]-nv_u,"ev":expected_value_decimal(probs["under"],under),"dq":data_quality,
             "confirmed":both_lineups_confirmed},
            {"section":"F5","market":f"F5 OVER {line:g}","p":probs["over"],"odds":over,
             "edge":probs["over"]-nv_o,"ev":expected_value_decimal(probs["over"],over),"dq":data_quality,
             "confirmed":both_lineups_confirmed},
        ]

    # Full game
    fg_ml_probs=moneyline_probabilities(away_fg,home_fg)
    no_tie=fg_ml_probs["away"]+fg_ml_probs["home"]
    p_a=fg_ml_probs["away"]/no_tie if no_tie else .5
    p_h=fg_ml_probs["home"]/no_tie if no_tie else .5
    fg_dq=max(35,data_quality-12) # módulo beta / bullpen proxy
    if use_fg_ml:
        nv_a,nv_h,_=no_vig_probs(fg_away_ml,fg_home_ml)
        markets += [
            {"section":"Full Game BETA","market":f"{game['away_abbr']} ML Full Game","p":p_a,"odds":fg_away_ml,
             "edge":p_a-nv_a,"ev":expected_value_decimal(p_a,fg_away_ml),"dq":fg_dq,"confirmed":False},
            {"section":"Full Game BETA","market":f"{game['home_abbr']} ML Full Game","p":p_h,"odds":fg_home_ml,
             "edge":p_h-nv_h,"ev":expected_value_decimal(p_h,fg_home_ml),"dq":fg_dq,"confirmed":False},
        ]
    if use_fg_total:
        probs=total_probabilities(fg_total,fg_market_line)
        nv_u,nv_o,_=no_vig_probs(fg_under,fg_over)
        markets += [
            {"section":"Full Game BETA","market":f"UNDER {fg_market_line:g} Full Game","p":probs["under"],"odds":fg_under,
             "edge":probs["under"]-nv_u,"ev":expected_value_decimal(probs["under"],fg_under),"dq":fg_dq,"confirmed":False},
            {"section":"Full Game BETA","market":f"OVER {fg_market_line:g} Full Game","p":probs["over"],"odds":fg_over,
             "edge":probs["over"]-nv_o,"ev":expected_value_decimal(probs["over"],fg_over),"dq":fg_dq,"confirmed":False},
        ]

    # Props seleccionados
    for label in selected_prop_labels:
        prop=next((p for p in all_props if p["label"]==label),None)
        if not prop: continue
        odds=prop_odds[label]
        res=evaluate_prop_odds(prop,odds)
        prop_dq=min(data_quality, prop.get("data_quality",70))
        # Edge vs probabilidad implícita simple; en props normalmente no tenemos lado opuesto para quitar vig.
        implied=1/odds
        markets.append({
            "section":"Props BETA","market":label,"p":prop["prob"],"odds":odds,
            "edge":prop["prob"]-implied,"ev":res["ev"],"dq":prop_dq,
            "confirmed":prop.get("confirmed",False),
            "safety":prop["safety"],"reason":prop["reason"]
        })

    # Clasificación
    for m in markets:
        max_strong = m["section"]=="F5"
        m["verdict"],m["confidence"]=grade_market(
            m["ev"],m["edge"],m["dq"],m["confirmed"],allow_strong=max_strong
        )
        m["fair_odds"]=prob_to_decimal(m["p"])
        m["min_odds"]=min_target_odds(m["p"])
        # Score de ranking penaliza beta, datos incompletos y mercados volátiles.
        beta_penalty=.90 if "BETA" in m["section"] else 1.0
        m["score"]=(m["ev"]*100)*beta_penalty*(m["dq"]/100)
    return markets

markets=build_market_candidates()
ranked=[m for m in sorted(markets,key=lambda x:x["score"],reverse=True)]

# ============================================================
# Tabs
# ============================================================
tabs=st.tabs(["🏆 Mejor apuesta","⏱️ Primeras 5","🕘 Juego completo","👤 Props","🔬 Datos del modelo"])

with tabs[0]:
    st.subheader(f"🏆 ¿Qué es lo mejor que puedo apostar en {game['away_abbr']} @ {game['home_abbr']}?")

    playable=[m for m in ranked if m["verdict"] in ("LEAN","PLAY","STRONG")]
    if not playable:
        st.info("⚪ PASS GENERAL — Con los momios capturados no encuentro una ventaja suficiente.")
    else:
        best=playable[0]
        if best["verdict"]=="STRONG":
            st.success(f"🔥 MEJOR APUESTA: {best['market']} @ {best['odds']:.2f}x")
        elif best["verdict"]=="PLAY":
            st.success(f"🟢 MEJOR APUESTA: {best['market']} @ {best['odds']:.2f}x")
        else:
            st.warning(f"🟡 MEJOR OPCIÓN ACTUAL: {best['market']} @ {best['odds']:.2f}x")

        b1,b2,b3,b4=st.columns(4)
        b1.metric("Prob. modelo",f"{best['p']*100:.1f}%")
        b2.metric("Cuota justa",f"{best['fair_odds']:.2f}x")
        b3.metric("EV",f"{best['ev']*100:+.1f}%")
        b4.metric("Calidad",f"{best['dq']}/100")
        if not best["confirmed"]:
            st.warning("⚠️ Esta recomendación sigue siendo provisional o pertenece a un módulo BETA.")

    st.markdown("### 🥇 Ranking general del partido")
    for i,m in enumerate(ranked[:12],1):
        icon={"STRONG":"🔥","PLAY":"🟢","LEAN":"🟡","PASS":"⚪"}[m["verdict"]]
        st.write(
            f"**{i}. {icon} {m['market']} @ {m['odds']:.2f}x** "
            f"— {m['section']} | Modelo {m['p']*100:.1f}% | "
            f"EV {m['ev']*100:+.1f}% | Cuota mín. {m['min_odds']:.2f}x | {m['verdict']}"
        )

    st.caption("El ranking solo compara mercados para los que capturaste una cuota. No inventa precios de Draftea.")

with tabs[1]:
    st.subheader("⏱️ Primeras 5")
    if not both_lineups_confirmed:
        st.warning("⚠️ Proyección provisional: falta al menos un lineup oficial.")
    c1,c2,c3=st.columns(3)
    c1.metric(game["away_abbr"],f"{away_f5:.2f}")
    c2.metric(game["home_abbr"],f"{home_f5:.2f}")
    c3.metric("Total F5",f"{f5_total:.2f}")

    f5_only=[m for m in ranked if m["section"]=="F5"]
    st.markdown("### Ranking F5")
    for i,m in enumerate(f5_only,1):
        st.write(
            f"**{i}. {m['market']} @ {m['odds']:.2f}x** — Modelo {m['p']*100:.1f}% | "
            f"Edge {m['edge']*100:+.1f} pp | EV {m['ev']*100:+.1f}% | {m['verdict']}"
        )

with tabs[2]:
    st.subheader("🕘 Juego completo")
    st.warning("⚠️ V4 usa un proxy de bullpen; sigue siendo BETA y no permite STRONG PLAY.")

    fg_lo,fg_hi=central_run_range(fg_total,.20,.80)
    c1,c2,c3,c4=st.columns(4)
    c1.metric(f"Proyección {game['away_abbr']}",f"{away_fg:.2f}")
    c2.metric(f"Proyección {game['home_abbr']}",f"{home_fg:.2f}")
    c3.metric("Total esperado",f"{fg_total:.2f}")
    c4.metric("Rango central",f"{fg_lo}–{fg_hi}")

    st.markdown("### 🤖 Modelo vs 🎰 Draftea")
    if use_fg_total:
        delta=fg_total-fg_market_line
        st.write(f"**Línea Draftea:** {fg_market_line:g}")
        st.write(f"**Proyección del modelo:** {fg_total:.2f}")
        st.write(f"**Diferencia:** {delta:+.2f} carreras")
        st.caption("Una diferencia de proyección no equivale por sí sola a valor; el momio decide el EV.")

    st.markdown("### 🧯 Bullpen proxy")
    p1,p2=st.columns(2)
    with p1:
        st.write(f"**{game['away_abbr']} staff/bullpen proxy**")
        if away_staff:
            st.caption(
                f"ERA staff {away_staff['era']:.2f} | WHIP {away_staff['whip']:.2f} | "
                f"RA/G últimos 10 {away_staff['recent_ra_pg']:.2f}"
            )
        else: st.caption("N/D")
    with p2:
        st.write(f"**{game['home_abbr']} staff/bullpen proxy**")
        if home_staff:
            st.caption(
                f"ERA staff {home_staff['era']:.2f} | WHIP {home_staff['whip']:.2f} | "
                f"RA/G últimos 10 {home_staff['recent_ra_pg']:.2f}"
            )
        else: st.caption("N/D")

    fg_only=[m for m in ranked if m["section"]=="Full Game BETA"]
    st.markdown("### Ranking Full Game")
    for i,m in enumerate(fg_only,1):
        st.write(
            f"**{i}. {m['market']} @ {m['odds']:.2f}x** — Modelo {m['p']*100:.1f}% | "
            f"EV {m['ev']*100:+.1f}% | {m['verdict']}"
        )

with tabs[3]:
    st.subheader("👤 Props de jugadores")
    if not both_lineups_confirmed:
        st.warning("⚠️ Bateadores provisionales hasta que estén los lineups. Pitcher Ks sí puede calcularse antes.")

    if not all_props:
        st.info("No hay datos suficientes para crear props.")
    else:
        categories=["Pitcher Ks","Pitcher Ks O/U","Hits","Total Bases","HRR","Home Run"]
        filt=st.multiselect("Filtrar mercado",categories,default=["Pitcher Ks","Hits","Total Bases"])
        filtered=[p for p in all_props if p["category"] in filt]
        filtered=sorted(filtered,key=lambda p:(p["safety"],p["prob"]),reverse=True)

        st.markdown("### 🔎 Qué mercados buscar en Draftea")
        for i,p in enumerate(filtered[:15],1):
            badge="🟢" if p["safety"]>=75 else "🟡" if p["safety"]>=60 else "⚪"
            state="CONFIRMADO" if p.get("confirmed") else "PROVISIONAL"
            st.write(
                f"**{i}. {badge} {p['label']}** — Modelo {p['prob']*100:.1f}% | "
                f"Seguridad {p['safety']}/100 | Cuota justa {prob_to_decimal(p['prob']):.2f}x | "
                f"🎯 Buscar ≥ {min_target_odds(p['prob']):.2f}x | {state}"
            )

        st.caption("La cuota mínima objetivo exige ~5% de EV; una cuota menor puede ser probable pero no apostable.")

        st.markdown("### Props que incluiste en el ranking general")
        if not selected_prop_labels:
            st.info("No seleccionaste props en el bloque de cuotas.")
        else:
            for label in selected_prop_labels:
                m=next((x for x in ranked if x["market"]==label),None)
                if m:
                    st.write(
                        f"**{label} @ {m['odds']:.2f}x** — Modelo {m['p']*100:.1f}% | "
                        f"EV {m['ev']*100:+.1f}% | {m['verdict']}"
                    )

with tabs[4]:
    st.subheader("🔬 Datos y transparencia")
    st.markdown("### Calidad de información")
    for n in quality_notes:
        st.write(n)
    st.write(f"**Puntuación global: {data_quality}/100**")

    st.markdown("### Lineups")
    l1,l2=st.columns(2)
    with l1:
        st.write(f"**{game['away_abbr']}** — {'Confirmado ✅' if away_confirmed else 'Pendiente ⚠️'}")
        for p in away_lineup[:9]:
            src="split" if p.get("used_split") else "temporada"
            st.caption(f"{p['order']}. {p['name']} | OPS {p['ops']:.3f} ({src})")
    with l2:
        st.write(f"**{game['home_abbr']}** — {'Confirmado ✅' if home_confirmed else 'Pendiente ⚠️'}")
        for p in home_lineup[:9]:
            src="split" if p.get("used_split") else "temporada"
            st.caption(f"{p['order']}. {p['name']} | OPS {p['ops']:.3f} ({src})")

    st.markdown("### Factores F5")
    st.json({
        game["away_abbr"]: away_f5_debug,
        game["home_abbr"]: home_f5_debug,
    })

    st.markdown("### Factores Full Game")
    st.json(fg_debug)

st.divider()
st.caption(
    "V4 experimental. F5 sigue siendo el módulo más desarrollado. Full Game y Props usan modelos BETA. "
    "La siguiente gran etapa debe ser Statcast + backtesting/calibración."
)
