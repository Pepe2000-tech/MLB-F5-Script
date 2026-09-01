import math

LEAGUE_RPG=4.40
LEAGUE_ERA=4.20
LEAGUE_WHIP=1.28
LEAGUE_K9=8.60
LEAGUE_BB9=3.20
LEAGUE_HR9=1.20
LEAGUE_OPS=.720
BASE_F5=LEAGUE_RPG*(5/9)

def clamp(x,lo,hi):return max(lo,min(hi,x))
def no_vig_probs(a,b):
    ia,ib=1/a,1/b;t=ia+ib
    return ia/t,ib/t,t-1
def expected_value_decimal(p,odds):return p*odds-1
def prob_to_decimal(p):return 1/p if p>0 else float("inf")
def poisson_pmf(k,lam):return math.exp(-lam)*(lam**k)/math.factorial(k)

def weather_factor(w):
    if not w:return 1.0
    f=1.0;t=w.get("temp_f",72);h=w.get("humidity",50);wind=w.get("wind_mph",5)
    if t>=90:f+=.025
    elif t>=82:f+=.015
    elif t<=50:f-=.020
    elif t<=58:f-=.010
    if h>=75:f+=.005
    if wind>=15:f+=.010
    return clamp(f,.95,1.06)

def pitcher_quality_factor(p):
    if not p:return 1.0
    era=clamp(p["era"]/LEAGUE_ERA,.65,1.55)
    whip=clamp(p["whip"]/LEAGUE_WHIP,.75,1.40)
    k=clamp(LEAGUE_K9/max(p["k9"],.1),.80,1.20)
    bb=clamp(p["bb9"]/LEAGUE_BB9,.75,1.30)
    hr=clamp(p["hr9"]/LEAGUE_HR9,.70,1.40)
    raw=.38*era+.22*whip+.16*k+.10*bb+.14*hr
    sample=clamp(p.get("games_started",0)/14,.30,1.0)
    return 1+(raw-1)*sample

def lineup_strength_factor(lineup,confirmed):
    if not lineup:return 1.0
    weights=[1.10,1.09,1.08,1.07,1.04,1.00,.96,.92,.89][:len(lineup)]
    ops=sum(p["ops"]*w for p,w in zip(lineup,weights))/sum(weights)
    ratio=clamp(ops/LEAGUE_OPS,.80,1.25)
    f=1+(ratio-1)*.35
    if not confirmed:f=1+(f-1)*.40
    return clamp(f,.92,1.08)

def project_f5_runs_v31(offense,opposing_pitcher,lineup,lineup_confirmed,park_factor=1.0,weather=None):
    blended=.70*offense["season_rpg"]+.30*offense["recent_rpg"]
    of=clamp(blended/LEAGUE_RPG,.70,1.35)
    pf=pitcher_quality_factor(opposing_pitcher)
    lf=lineup_strength_factor(lineup,lineup_confirmed)
    park=clamp(park_factor,.92,1.12)
    wf=weather_factor(weather)
    proj=clamp(BASE_F5*of*pf*lf*park*wf,.60,4.50)
    return proj,{"offense_factor":of,"pitcher_factor":pf,"lineup_factor":lf,"park_factor":park,"weather_factor":wf}

def project_full_game_runs(away_form,home_form,away_pitch,home_pitch,park_factor=1.0,weather=None):
    # Beta: mezcla ofensiva + starter + regresión a bullpen promedio.
    park=clamp(park_factor,.92,1.12);wf=weather_factor(weather)
    af=(.75*away_form["season_rpg"]+.25*away_form["recent_rpg"])
    hf=(.75*home_form["season_rpg"]+.25*home_form["recent_rpg"])
    apf=pitcher_quality_factor(home_pitch)
    hpf=pitcher_quality_factor(away_pitch)
    # Starter pesa aprox 58% del juego, resto regresión a promedio.
    away=af*(.58*apf+.42*1.0)*park*wf
    home=hf*(.58*hpf+.42*1.0)*park*wf
    return clamp(away,2.0,8.5),clamp(home,2.0,8.5)

def total_probabilities(lam,line):
    u=o=push=0.0
    for k in range(0,25):
        p=poisson_pmf(k,lam)
        if k<line:u+=p
        elif k>line:o+=p
        else:push+=p
    t=u+o+push
    if t:u/=t;o/=t;push/=t
    if abs(line-round(line))<1e-9 and (u+o)>0:
        nt=u+o;u/=nt;o/=nt
    return {"under":u,"over":o,"push":push}

def moneyline_probabilities(la,lh,max_runs=18):
    a=h=tie=0.0
    for x in range(max_runs+1):
        px=poisson_pmf(x,la)
        for y in range(max_runs+1):
            py=poisson_pmf(y,lh);p=px*py
            if x>y:a+=p
            elif y>x:h+=p
            else:tie+=p
    s=a+h+tie
    if s:a/=s;h/=s;tie/=s
    return {"away":a,"home":h,"tie":tie}

def grade_pick(ev,edge,dq,lineups_confirmed=False):
    if dq<60:return "PASS","Baja"
    if not lineups_confirmed:
        if ev>=.06 and edge>=.035 and dq>=70:return "PLAY","Provisional"
        if ev>=.02 and edge>=.015 and dq>=60:return "LEAN","Provisional"
        return "PASS","Provisional"
    if ev>=.12 and edge>=.06 and dq>=85:return "STRONG","Alta"
    if ev>=.06 and edge>=.035 and dq>=75:return "PLAY","Media-Alta"
    if ev>=.02 and edge>=.015 and dq>=65:return "LEAN","Media"
    return "PASS","Baja"

def prob_at_least_one(event_rate,expected_pa):
    event_rate=clamp(event_rate,0,0.95)
    return 1-(1-event_rate)**expected_pa

def poisson_tail(lam,threshold):
    # P(X >= threshold)
    if threshold<=0:return 1.0
    return 1-sum(poisson_pmf(k,lam) for k in range(threshold))

def expected_pa(order):
    return {1:4.55,2:4.50,3:4.45,4:4.35,5:4.25,6:4.10,7:4.00,8:3.90,9:3.80}.get(order,4.10)

def build_prop_candidates(away_pitcher,home_pitcher,away_pitcher_name,home_pitcher_name,away_lineup,home_lineup,away_team,home_team):
    props=[]

    # Pitcher Ks: 4+,5+,6+,7+
    for name,p,opp_lineup,team in [
        (away_pitcher_name,away_pitcher,home_lineup,away_team),
        (home_pitcher_name,home_pitcher,away_lineup,home_team),
    ]:
        if p:
            # Ajuste sencillo por K-rate promedio de lineup rival si está disponible.
            opp_k=.22
            valid=[x.get("k_rate") for x in opp_lineup if x.get("stats_available")]
            if valid:opp_k=sum(valid)/len(valid)
            k_adj=clamp(opp_k/.22,.85,1.18)
            mean_k=p["k9"]*p.get("expected_ip",5.2)/9*k_adj
            for th in [4,5,6,7]:
                prob=poisson_tail(mean_k,th)
                safety=round(clamp(prob*100 + (8 if th<=5 else 0),35,92))
                props.append({
                    "category":"Pitcher Ks",
                    "label":f"{name} {th}+ ponches",
                    "prob":prob,
                    "safety":safety,
                    "reason":f"Media proyectada de ponches ~{mean_k:.1f}; ajustada por K-rate del lineup rival."
                })

    def add_hitters(lineup,team):
        for p in lineup[:9]:
            if not p.get("stats_available"):continue
            pa=expected_pa(p["order"])
            # Hits 1+,2+
            mean_hits=p["hit_rate"]*pa
            p1=poisson_tail(mean_hits,1)
            p2=poisson_tail(mean_hits,2)
            props.append({"category":"Hits","label":f"{p['name']} 1+ hit","prob":p1,"safety":round(clamp(p1*100,35,95)),
                          "reason":f"Proyección por tasa de hits y ~{pa:.1f} PA esperadas desde el turno #{p['order']}."})
            props.append({"category":"Hits","label":f"{p['name']} 2+ hits","prob":p2,"safety":round(clamp(p2*100,25,85)),
                          "reason":f"Prop más agresivo basado en media de hits proyectada {mean_hits:.2f}."})

            # Total Bases 1+,2+
            mean_tb=p["tb_rate"]*pa
            tb1=poisson_tail(mean_tb,1)
            tb2=poisson_tail(mean_tb,2)
            props.append({"category":"Total Bases","label":f"{p['name']} 1+ base total","prob":tb1,"safety":round(clamp(tb1*100,35,95)),
                          "reason":f"Media proyectada de bases totales ~{mean_tb:.2f}."})
            props.append({"category":"Total Bases","label":f"{p['name']} 2+ bases totales","prob":tb2,"safety":round(clamp(tb2*100,25,88)),
                          "reason":f"Prop agresivo usando tasa de TB por aparición."})

            # HRR 2+
            mean_hrr=p["hrr_rate"]*pa
            hrr2=poisson_tail(mean_hrr,2)
            props.append({"category":"HRR","label":f"{p['name']} 2+ HRR","prob":hrr2,"safety":round(clamp(hrr2*100,25,88)),
                          "reason":f"Aproximación Hits+Runs+RBI con media ~{mean_hrr:.2f}."})

            # HR 1+
            hrp=prob_at_least_one(p["hr_rate"],pa)
            props.append({"category":"Home Run","label":f"{p['name']} 1+ HR","prob":hrp,"safety":round(clamp(hrp*100,10,70)),
                          "reason":f"HR es un mercado volátil; cálculo por HR/PA y ~{pa:.1f} PA esperadas."})

    add_hitters(away_lineup,away_team)
    add_hitters(home_lineup,home_team)
    return props

def evaluate_prop_odds(prop,odds):
    p=prop["prob"]
    ev=p*odds-1
    fair=prob_to_decimal(p)
    if ev>=.15 and prop["safety"]>=75:verdict="STRONG"
    elif ev>=.08 and prop["safety"]>=65:verdict="PLAY"
    elif ev>=.03 and prop["safety"]>=55:verdict="LEAN"
    else:verdict="PASS"
    return {"ev":ev,"fair_odds":fair,"verdict":verdict}
