from datetime import date, datetime, timedelta
import math
import requests
# ============================================================
# MLB BETTING HUB V4.1.1
# HOTFIX SINGLE-FILE:
# Toda la lógica de datos + modelo vive dentro de app.py.
# Esto evita errores de importación entre app.py/model.py/data_mlb.py.
# ============================================================


# ================= DATA LAYER =================
BASE="https://statsapi.mlb.com/api/v1"
HEADERS={"User-Agent":"MLB-Betting-Hub/4.1"}

STADIUMS={
"ARI":{"lat":33.4455,"lon":-112.0667,"factor":1.03,"name":"Chase Field"},
"ATL":{"lat":33.8907,"lon":-84.4677,"factor":1.01,"name":"Truist Park"},
"BAL":{"lat":39.2839,"lon":-76.6217,"factor":0.97,"name":"Camden Yards"},
"BOS":{"lat":42.3467,"lon":-71.0972,"factor":1.05,"name":"Fenway Park"},
"CHC":{"lat":41.9484,"lon":-87.6553,"factor":1.03,"name":"Wrigley Field"},
"CWS":{"lat":41.8300,"lon":-87.6338,"factor":1.01,"name":"Rate Field"},
"CIN":{"lat":39.0979,"lon":-84.5082,"factor":1.08,"name":"Great American Ball Park"},
"CLE":{"lat":41.4962,"lon":-81.6852,"factor":0.97,"name":"Progressive Field"},
"COL":{"lat":39.7559,"lon":-104.9942,"factor":1.14,"name":"Coors Field"},
"DET":{"lat":42.3390,"lon":-83.0485,"factor":0.98,"name":"Comerica Park"},
"HOU":{"lat":29.7573,"lon":-95.3555,"factor":1.00,"name":"Daikin Park"},
"KC":{"lat":39.0517,"lon":-94.4803,"factor":0.97,"name":"Kauffman Stadium"},
"LAA":{"lat":33.8003,"lon":-117.8827,"factor":0.98,"name":"Angel Stadium"},
"LAD":{"lat":34.0739,"lon":-118.2400,"factor":1.00,"name":"Dodger Stadium"},
"MIA":{"lat":25.7781,"lon":-80.2197,"factor":0.96,"name":"loanDepot park"},
"MIL":{"lat":43.0280,"lon":-87.9712,"factor":1.01,"name":"American Family Field"},
"MIN":{"lat":44.9817,"lon":-93.2776,"factor":0.99,"name":"Target Field"},
"NYM":{"lat":40.7571,"lon":-73.8458,"factor":0.97,"name":"Citi Field"},
"NYY":{"lat":40.8296,"lon":-73.9262,"factor":1.04,"name":"Yankee Stadium"},
"ATH":{"lat":38.5803,"lon":-121.5130,"factor":1.00,"name":"Sutter Health Park"},
"PHI":{"lat":39.9061,"lon":-75.1665,"factor":1.04,"name":"Citizens Bank Park"},
"PIT":{"lat":40.4469,"lon":-80.0057,"factor":0.96,"name":"PNC Park"},
"SD":{"lat":32.7076,"lon":-117.1570,"factor":0.94,"name":"Petco Park"},
"SF":{"lat":37.7786,"lon":-122.3893,"factor":0.95,"name":"Oracle Park"},
"SEA":{"lat":47.5914,"lon":-122.3325,"factor":0.96,"name":"T-Mobile Park"},
"STL":{"lat":38.6226,"lon":-90.1928,"factor":0.98,"name":"Busch Stadium"},
"TB":{"lat":27.7683,"lon":-82.6534,"factor":0.97,"name":"George M. Steinbrenner Field"},
"TEX":{"lat":32.7473,"lon":-97.0847,"factor":1.00,"name":"Globe Life Field"},
"TOR":{"lat":43.6414,"lon":-79.3894,"factor":1.01,"name":"Rogers Centre"},
"WSH":{"lat":38.8730,"lon":-77.0074,"factor":0.99,"name":"Nationals Park"},
}

def _get(url,params=None):
    r=requests.get(url,params=params,headers=HEADERS,timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=120)
def get_schedule(date_str):
    try:
        data=_get(f"{BASE}/schedule",{"sportId":1,"date":date_str,"hydrate":"probablePitcher,team,venue"})
    except Exception:return []
    out=[]
    for d in data.get("dates",[]):
        for g in d.get("games",[]):
            teams=g.get("teams",{})
            away=teams.get("away",{}).get("team",{})
            home=teams.get("home",{}).get("team",{})
            app=teams.get("away",{}).get("probablePitcher") or {}
            hpp=teams.get("home",{}).get("probablePitcher") or {}
            aa=away.get("abbreviation") or away.get("teamName") or "AWAY"
            ha=home.get("abbreviation") or home.get("teamName") or "HOME"
            out.append({
                "game_pk":g.get("gamePk"),"away_id":away.get("id"),"home_id":home.get("id"),
                "away_abbr":aa,"home_abbr":ha,
                "away_pitcher_id":app.get("id"),"home_pitcher_id":hpp.get("id"),
                "away_pitcher_name":app.get("fullName","TBD"),
                "home_pitcher_name":hpp.get("fullName","TBD"),
                "label":f"{aa} @ {ha}","game_time_local":g.get("gameDate"),
            })
    return out

@st.cache_data(ttl=1800)
def get_pitcher_stats(player_id,season):
    if not player_id:return None
    try:
        person=_get(f"{BASE}/people/{player_id}").get("people",[{}])[0]
        hand=(person.get("pitchHand") or {}).get("code","R")
    except Exception:hand="R"
    try:
        data=_get(f"{BASE}/people/{player_id}/stats",{"stats":"season","group":"pitching","season":season})
        splits=data.get("stats",[{}])[0].get("splits",[])
        if not splits:return None
        s=splits[0].get("stat",{})
        ip=float(s.get("inningsPitched",0) or 0)
        so=float(s.get("strikeOuts",0) or 0)
        bb=float(s.get("baseOnBalls",0) or 0)
        hr=float(s.get("homeRuns",0) or 0)
        gs=int(s.get("gamesStarted",0) or 0)
        return {
            "hand":hand,"era":float(s.get("era",4.2) or 4.2),"whip":float(s.get("whip",1.28) or 1.28),
            "innings":ip,"games_started":gs,
            "k9":so*9/ip if ip else 8.6,"bb9":bb*9/ip if ip else 3.2,"hr9":hr*9/ip if ip else 1.2,
            "strikeouts":so,"expected_ip":min(6.3,max(4.5,ip/gs if gs else 5.2)),
        }
    except Exception:return None

@st.cache_data(ttl=1800)
def get_team_form(team_id,target_date):
    target=datetime.strptime(target_date,"%Y-%m-%d").date()
    start=target.replace(month=3,day=20);end=target-timedelta(days=1)
    fb={"season_rpg":4.4,"recent_rpg":4.4,"games":0,"recent_games":0}
    if end<start:return fb
    try:
        data=_get(f"{BASE}/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat(),"gameType":"R"})
    except Exception:return fb
    rows=[]
    for d in data.get("dates",[]):
        for g in d.get("games",[]):
            if g.get("status",{}).get("abstractGameState")!="Final":continue
            teams=g.get("teams",{});a=teams.get("away",{});h=teams.get("home",{})
            if a.get("team",{}).get("id")==team_id:r=a.get("score")
            elif h.get("team",{}).get("id")==team_id:r=h.get("score")
            else:continue
            if r is not None:rows.append(float(r))
    if not rows:return fb
    recent=rows[-15:]
    return {"season_rpg":sum(rows)/len(rows),"recent_rpg":sum(recent)/len(recent),"games":len(rows),"recent_games":len(recent)}

@st.cache_data(ttl=1800)
def get_team_pitching_profile(team_id,season,target_date):
    try:
        data=_get(f"{BASE}/teams/{team_id}/stats",{"stats":"season","group":"pitching","season":season})
        splits=data.get("stats",[{}])[0].get("splits",[])
        s=splits[0].get("stat",{}) if splits else {}
        era=float(s.get("era",4.20) or 4.20)
        whip=float(s.get("whip",1.28) or 1.28)
    except Exception:
        era,whip=4.20,1.28

    target=datetime.strptime(target_date,"%Y-%m-%d").date()
    start=target-timedelta(days=18);end=target-timedelta(days=1)
    allowed=[]
    try:
        sched=_get(f"{BASE}/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat(),"gameType":"R"})
        for d in sched.get("dates",[]):
            for g in d.get("games",[]):
                if g.get("status",{}).get("abstractGameState")!="Final":continue
                teams=g.get("teams",{});a=teams.get("away",{});h=teams.get("home",{})
                if a.get("team",{}).get("id")==team_id:r=h.get("score")
                elif h.get("team",{}).get("id")==team_id:r=a.get("score")
                else:continue
                if r is not None:allowed.append(float(r))
    except Exception:pass

    recent=allowed[-10:]
    recent_ra=sum(recent)/len(recent) if recent else 4.4
    return {"era":era,"whip":whip,"recent_ra_pg":recent_ra}

@st.cache_data(ttl=60)
def get_lineups(game_pk):
    if not game_pk:return {"away":[],"home":[]}
    try:box=_get(f"{BASE}/game/{game_pk}/boxscore")
    except Exception:return {"away":[],"home":[]}
    result={}
    for side in ["away","home"]:
        team=(box.get("teams") or {}).get(side,{})
        players=team.get("players",{});order=team.get("battingOrder",[]) or []
        lineup=[]
        for idx,pid in enumerate(order[:9],1):
            pd=players.get(f"ID{pid}",{});person=pd.get("person",{})
            lineup.append({"id":pid,"name":person.get("fullName",f"Player {pid}"),"order":idx})
        result[side]=lineup
    return result

def _f(v,d=0.0):
    try:return float(v)
    except:return d

@st.cache_data(ttl=1800)
def get_hitter_stats(player_id,season,opposing_hand="R"):
    overall=None
    try:
        data=_get(f"{BASE}/people/{player_id}/stats",{"stats":"season","group":"hitting","season":season})
        splits=data.get("stats",[{}])[0].get("splits",[])
        if splits:
            s=splits[0].get("stat",{})
            pa=int(s.get("plateAppearances",0) or 0)
            overall={
                "ops":_f(s.get("ops"),.720),"pa":pa,"ab":int(s.get("atBats",0) or 0),
                "hits":int(s.get("hits",0) or 0),"hr":int(s.get("homeRuns",0) or 0),
                "runs":int(s.get("runs",0) or 0),"rbi":int(s.get("rbi",0) or 0),
                "tb":int(s.get("totalBases",0) or 0),"so":int(s.get("strikeOuts",0) or 0)
            }
    except Exception:pass

    split=None;sit="vr" if opposing_hand=="R" else "vl"
    try:
        hydrate=f"stats(group=hitting,type=statSplits,sitCodes=[{sit}],season={season})"
        pdata=_get(f"{BASE}/people",{"personIds":player_id,"hydrate":hydrate})
        people=pdata.get("people",[])
        if people:
            for sg in people[0].get("stats",[]):
                for sp in sg.get("splits",[]):
                    s=sp.get("stat",{});pa=int(s.get("plateAppearances",0) or 0);ops=_f(s.get("ops"),0)
                    if ops>0:split={"ops":ops,"pa":pa};break
                if split:break
    except Exception:split=None

    if not overall:
        return {"ops":.720,"pa":0,"hits":0,"hr":0,"runs":0,"rbi":0,"tb":0,"so":0,
                "hit_rate":.22,"hr_rate":.03,"tb_rate":.32,"hrr_rate":.42,"k_rate":.22,
                "used_split":False,"stats_available":False}

    pa=max(overall["pa"],1)
    ops=split["ops"] if split and split["pa"]>=30 else overall["ops"]
    return {**overall,"ops":ops,
            "hit_rate":overall["hits"]/pa,"hr_rate":overall["hr"]/pa,"tb_rate":overall["tb"]/pa,
            "hrr_rate":(overall["hits"]+overall["runs"]+overall["rbi"])/pa,"k_rate":overall["so"]/pa,
            "used_split":bool(split and split["pa"]>=30),"stats_available":True}

def enrich_lineup(lineup,season,opposing_hand):
    return [{**item,**get_hitter_stats(item["id"],season,opposing_hand)} for item in lineup[:9]]

def get_stadium_context(home_abbr):return STADIUMS.get(home_abbr)

@st.cache_data(ttl=1200)
def get_weather(lat,lon,date_str,game_time=None):
    try:
        data=requests.get("https://api.open-meteo.com/v1/forecast",params={
            "latitude":lat,"longitude":lon,
            "hourly":"temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation_probability",
            "temperature_unit":"fahrenheit","wind_speed_unit":"mph","timezone":"auto",
            "start_date":date_str,"end_date":date_str},timeout=15).json()
        h=data.get("hourly",{});temps=h.get("temperature_2m",[])
        if not temps:return None
        idx=min(18,len(temps)-1);hum=h.get("relative_humidity_2m",[]);wind=h.get("wind_speed_10m",[])
        pop=h.get("precipitation_probability",[])
        return {"temp_f":float(temps[idx]),"humidity":float(hum[idx]) if idx<len(hum) else 50,
                "wind_mph":float(wind[idx]) if idx<len(wind) else 5,
                "precip_probability":float(pop[idx]) if idx<len(pop) else 0}
    except Exception:return None

# ================= MODEL LAYER =================
LEAGUE_RPG=4.40; LEAGUE_ERA=4.20; LEAGUE_WHIP=1.28
LEAGUE_K9=8.60; LEAGUE_BB9=3.20; LEAGUE_HR9=1.20; LEAGUE_OPS=.720
BASE_F5=LEAGUE_RPG*(5/9); BASE_REST=LEAGUE_RPG*(4/9)

def clamp(x,lo,hi):return max(lo,min(hi,x))
def expected_value_decimal(p,odds):return p*odds-1
def prob_to_decimal(p):return 1/p if p>0 else float("inf")
def min_target_odds(p,target_ev=.05):return (1+target_ev)/p if p>0 else float("inf")
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

def offense_factor(offense):
    blended=.70*offense["season_rpg"]+.30*offense["recent_rpg"]
    return clamp(blended/LEAGUE_RPG,.70,1.35)

def project_f5_runs(offense,opposing_pitcher,lineup,lineup_confirmed,park_factor=1.0,weather=None):
    of=offense_factor(offense);pf=pitcher_quality_factor(opposing_pitcher)
    lf=lineup_strength_factor(lineup,lineup_confirmed)
    park=clamp(park_factor,.92,1.12);wf=weather_factor(weather)
    proj=clamp(BASE_F5*of*pf*lf*park*wf,.60,4.50)
    return proj,{"offense_factor":round(of,3),"pitcher_factor":round(pf,3),
                 "lineup_factor":round(lf,3),"park_factor":round(park,3),
                 "weather_factor":round(wf,3),"projected_runs":round(proj,3)}

def staff_proxy_factor(staff):
    if not staff:return 1.0
    era=clamp(staff["era"]/LEAGUE_ERA,.75,1.35)
    whip=clamp(staff["whip"]/LEAGUE_WHIP,.80,1.30)
    recent=clamp(staff["recent_ra_pg"]/LEAGUE_RPG,.75,1.35)
    return clamp(.45*era+.20*whip+.35*recent,.78,1.30)

def project_full_game_runs_v4(away_f5,home_f5,away_form,home_form,away_staff,home_staff,park_factor=1.0,weather=None):
    park=clamp(park_factor,.92,1.12);wf=weather_factor(weather)
    away_of=offense_factor(away_form);home_of=offense_factor(home_form)
    home_bp=staff_proxy_factor(home_staff);away_bp=staff_proxy_factor(away_staff)
    away_rest=BASE_REST*away_of*home_bp*park*wf
    home_rest=BASE_REST*home_of*away_bp*park*wf
    away=clamp(away_f5+away_rest,1.5,9.5)
    home=clamp(home_f5+home_rest,1.5,9.5)
    return away,home,{
        "away_f5":round(away_f5,3),"home_f5":round(home_f5,3),
        "away_remaining_innings":round(away_rest,3),"home_remaining_innings":round(home_rest,3),
        "home_staff_factor":round(home_bp,3),"away_staff_factor":round(away_bp,3)
    }

def total_probabilities(lam,line):
    u=o=push=0.0
    for k in range(0,30):
        p=poisson_pmf(k,lam)
        if k<line:u+=p
        elif k>line:o+=p
        else:push+=p
    t=u+o+push
    if t:u/=t;o/=t;push/=t
    if abs(line-round(line))<1e-9 and (u+o)>0:
        nt=u+o;u/=nt;o/=nt
    return {"under":u,"over":o,"push":push}

def moneyline_probabilities(la,lh,max_runs=20):
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

def central_run_range(lam,low=.20,high=.80):
    cdf=0.0;lo=0;hi=0;lo_found=False
    for k in range(0,35):
        cdf+=poisson_pmf(k,lam)
        if not lo_found and cdf>=low:
            lo=k;lo_found=True
        if cdf>=high:
            hi=k;break
    return lo,hi

def poisson_tail(lam,threshold):
    if threshold<=0:return 1.0
    return 1-sum(poisson_pmf(k,lam) for k in range(threshold))

def expected_pa(order):
    return {1:4.55,2:4.50,3:4.45,4:4.35,5:4.25,6:4.10,7:4.00,8:3.90,9:3.80}.get(order,4.10)

def prob_at_least_one(rate,pa):
    rate=clamp(rate,0,.95)
    return 1-(1-rate)**pa

def build_prop_candidates(away_pitcher,home_pitcher,away_pitcher_name,home_pitcher_name,
                          away_lineup,home_lineup,away_team,home_team,lineups_confirmed=False):
    props=[]
    for name,p,opp_lineup in [
        (away_pitcher_name,away_pitcher,home_lineup),
        (home_pitcher_name,home_pitcher,away_lineup),
    ]:
        if p:
            opp_k=.22
            vals=[x.get("k_rate") for x in opp_lineup if x.get("stats_available")]
            if vals:opp_k=sum(vals)/len(vals)
            k_adj=clamp(opp_k/.22,.85,1.18)
            mean_k=p["k9"]*p.get("expected_ip",5.2)/9*k_adj
            for th in [4,5,6]:
                prob=poisson_tail(mean_k,th)
                props.append({
                    "category":"Pitcher Ks",
                    "label":f"{name} {th}+ ponches",
                    "prob":prob,
                    "reason":f"Media proyectada ~{mean_k:.1f} K; ajustada por K-rate rival.",
                    "confirmed":True,
                    "data_quality":78
                })

    def add_hitters(lineup):
        for p in lineup[:9]:
            if not p.get("stats_available"): continue
            pa=expected_pa(p["order"])
            confirmed=lineups_confirmed
            dq=82 if confirmed else 60

            mean_hits=p["hit_rate"]*pa
            p1=poisson_tail(mean_hits,1)
            p2=poisson_tail(mean_hits,2)
            props += [
                {"category":"Hits","label":f"{p['name']} 1+ hit","prob":p1,
                 "reason":f"~{pa:.1f} PA desde turno #{p['order']}; media hits ~{mean_hits:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
                {"category":"Hits","label":f"{p['name']} 2+ hits","prob":p2,
                 "reason":f"~{pa:.1f} PA desde turno #{p['order']}; media hits ~{mean_hits:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
            ]

            mean_tb=p["tb_rate"]*pa
            ptb1=poisson_tail(mean_tb,1)
            ptb2=poisson_tail(mean_tb,2)
            props += [
                {"category":"Total Bases","label":f"{p['name']} 1+ base total","prob":ptb1,
                 "reason":f"Media TB ~{mean_tb:.2f}; turno #{p['order']}.",
                 "confirmed":confirmed,"data_quality":dq},
                {"category":"Total Bases","label":f"{p['name']} 2+ bases totales","prob":ptb2,
                 "reason":f"Media TB ~{mean_tb:.2f}; turno #{p['order']}.",
                 "confirmed":confirmed,"data_quality":dq},
            ]

            mean_hrr=p["hrr_rate"]*pa
            phrr=poisson_tail(mean_hrr,2)
            props.append({"category":"HRR","label":f"{p['name']} 2+ HRR","prob":phrr,
                          "reason":f"Media H+R+RBI ~{mean_hrr:.2f}.",
                          "confirmed":confirmed,"data_quality":dq})

            phr=prob_at_least_one(p["hr_rate"],pa)
            props.append({"category":"Home Run","label":f"{p['name']} 1+ HR","prob":phr,
                          "reason":f"Mercado de alta varianza; ~{pa:.1f} PA esperadas.",
                          "confirmed":confirmed,"data_quality":max(50,dq-10)})

    add_hitters(away_lineup)
    add_hitters(home_lineup)
    return props

def _auto_score(item):
    p=item["prob"]
    q=item.get("quality",65)/100
    confirmed=item.get("confirmed",False)
    volatility=item.get("volatility","medium")

    # Queremos "qué buscar" antes de conocer el momio:
    # priorizamos probabilidad + calidad + estabilidad, no EV.
    prob_component = clamp((p-.48)/.32, 0, 1)
    conf_component = q
    confirmed_bonus = .06 if confirmed else 0
    volatility_penalty = .10 if volatility=="high" else .03 if volatility=="medium" else 0
    beta_penalty = .08 if "BETA" in item.get("category","") else 0
    return prob_component*.62 + conf_component*.32 + confirmed_bonus - volatility_penalty - beta_penalty

def rank_automatic_candidates(items,max_items=5):
    ranked=[]
    for item in items:
        if item["prob"] < .54:
            continue
        x=dict(item)
        x["auto_score"]=_auto_score(x)
        if x["auto_score"]>=.62:
            x["auto_grade"]="ALTA"
        elif x["auto_score"]>=.48:
            x["auto_grade"]="MEDIA"
        else:
            x["auto_grade"]="BAJA"
        ranked.append(x)

    ranked=sorted(ranked,key=lambda x:(x["auto_score"],x["prob"]),reverse=True)

    # Diversidad: no queremos 5 props casi iguales del mismo pitcher/jugador.
    selected=[]
    seen_prefix={}
    for item in ranked:
        prefix=item["label"].split(" 1+")[0].split(" 2+")[0].split(" 3+")[0].split(" 4+")[0].split(" 5+")[0].split(" 6+")[0]
        count=seen_prefix.get(prefix,0)
        if count>=2:
            continue
        selected.append(item)
        seen_prefix[prefix]=count+1
        if len(selected)>=max_items:
            break
    return selected

def evaluate_selected_candidate(item,odds):
    p=item["prob"]
    ev=expected_value_decimal(p,odds)
    fair=prob_to_decimal(p)
    target=min_target_odds(p)
    edge_price = odds/target - 1

    if ev>=.08 and odds>=target:
        verdict="APOSTAR"
    elif ev>=.03 and odds>=fair:
        verdict="LEAN"
    else:
        verdict="PASS"

    quality=item.get("quality",65)/100
    score=ev*quality
    if not item.get("confirmed",False):
        score*=.88

    return {
        "ev":ev,
        "fair_odds":fair,
        "target_odds":target,
        "edge_price":edge_price,
        "verdict":verdict,
        "score":score
    }

# ================= APP UI =================
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