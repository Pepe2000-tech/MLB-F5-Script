from datetime import date, datetime, timedelta
import math
import hashlib
import requests
import numpy as np
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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
        bf=float(s.get("battersFaced",0) or 0)
        return {
            "hand":hand,"era":float(s.get("era",4.2) or 4.2),"whip":float(s.get("whip",1.28) or 1.28),
            "innings":ip,"games_started":gs,"batters_faced":bf,
            "k9":so*9/ip if ip else 8.6,"bb9":bb*9/ip if ip else 3.2,"hr9":hr*9/ip if ip else 1.2,
            "strikeouts":so,"walks":bb,"home_runs":hr,
            "k_rate":so/bf if bf else None,
            "bb_rate":bb/bf if bf else None,
            "expected_ip":min(6.3,max(4.5,ip/gs if gs else 5.2)),
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



# ================= MODEL LAYER V5 =================
LEAGUE_RPG=4.40
LEAGUE_ERA=4.20
LEAGUE_WHIP=1.28
LEAGUE_K9=8.60
LEAGUE_BB9=3.20
LEAGUE_HR9=1.20
LEAGUE_OPS=.720
LEAGUE_HIT_PA=.225
LEAGUE_TB_PA=.335
LEAGUE_HR_PA=.032
LEAGUE_K_PA=.222
BASE_F5=LEAGUE_RPG*(5/9)
BASE_REST=LEAGUE_RPG*(4/9)

def clamp(x,lo,hi):
    return max(lo,min(hi,x))

def expected_value_decimal(p,odds):
    return p*odds-1

def prob_to_decimal(p):
    return 1/p if p>0 else float("inf")

def min_target_odds(p,target_ev=.05):
    return (1+target_ev)/p if p>0 else float("inf")

def stable_seed(*parts):
    raw="|".join(str(x) for x in parts).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8],16)

def shrink_mean(observed, sample_n, prior_mean, prior_n):
    sample_n=max(float(sample_n or 0),0)
    return (observed*sample_n + prior_mean*prior_n)/(sample_n+prior_n)

def weather_factor(w):
    if not w:
        return 1.0
    f=1.0
    t=w.get("temp_f",72)
    h=w.get("humidity",50)
    wind=w.get("wind_mph",5)
    rain=w.get("precip_probability",0)
    if t>=90:f+=.025
    elif t>=82:f+=.012
    elif t<=50:f-=.018
    elif t<=58:f-=.010
    if h>=75:f+=.004
    if wind>=15:f+=.008
    if rain>=60:f-=.006
    return clamp(f,.95,1.055)

def offense_components(offense):
    season=offense.get("season_rpg",LEAGUE_RPG)
    recent=offense.get("recent_rpg",season)
    games=max(offense.get("games",0),1)
    recent_games=max(offense.get("recent_games",0),1)

    season_reg=shrink_mean(season,games,LEAGUE_RPG,25)
    recent_reg=shrink_mean(recent,recent_games,season_reg,18)

    conservative=.78*season_reg+.22*LEAGUE_RPG
    balanced=.72*season_reg+.28*recent_reg
    recent_sensitive=.58*season_reg+.42*recent_reg

    return {
        "conservative":clamp(conservative/LEAGUE_RPG,.78,1.26),
        "balanced":clamp(balanced/LEAGUE_RPG,.76,1.30),
        "recent":clamp(recent_sensitive/LEAGUE_RPG,.74,1.34),
        "season_reg":season_reg,
        "recent_reg":recent_reg,
    }

def pitcher_components(p):
    if not p:
        return {"conservative":1.0,"balanced":1.0,"skills":1.0,"sample":0.35}

    ip=max(float(p.get("innings",0) or 0),0)
    gs=max(int(p.get("games_started",0) or 0),0)
    sample=clamp(ip/90,.25,1.0)

    era=shrink_mean(float(p.get("era",LEAGUE_ERA)),ip,LEAGUE_ERA,45)
    whip=shrink_mean(float(p.get("whip",LEAGUE_WHIP)),ip,LEAGUE_WHIP,50)
    k9=shrink_mean(float(p.get("k9",LEAGUE_K9)),ip,LEAGUE_K9,45)
    bb9=shrink_mean(float(p.get("bb9",LEAGUE_BB9)),ip,LEAGUE_BB9,45)
    hr9=shrink_mean(float(p.get("hr9",LEAGUE_HR9)),ip,LEAGUE_HR9,50)

    era_f=clamp(era/LEAGUE_ERA,.72,1.38)
    whip_f=clamp(whip/LEAGUE_WHIP,.78,1.30)
    k_f=clamp(LEAGUE_K9/max(k9,.1),.82,1.18)
    bb_f=clamp(bb9/LEAGUE_BB9,.78,1.24)
    hr_f=clamp(hr9/LEAGUE_HR9,.78,1.28)

    conservative=.52*era_f+.26*whip_f+.12*k_f+.10*bb_f
    balanced=.34*era_f+.25*whip_f+.18*k_f+.10*bb_f+.13*hr_f
    skills=.20*era_f+.20*whip_f+.27*k_f+.14*bb_f+.19*hr_f

    # Partial regression of extreme factor toward neutral when sample is small.
    def reg(f):
        return 1+(f-1)*sample

    return {
        "conservative":clamp(reg(conservative),.76,1.34),
        "balanced":clamp(reg(balanced),.74,1.36),
        "skills":clamp(reg(skills),.73,1.38),
        "sample":sample,
        "era_reg":era,"whip_reg":whip,"k9_reg":k9,"bb9_reg":bb9,"hr9_reg":hr9
    }

def lineup_component(lineup,confirmed):
    if not lineup:
        return {"factor":1.0,"quality":0.45,"ops":LEAGUE_OPS}
    weights=[1.12,1.10,1.08,1.06,1.03,1.00,.97,.94,.91][:len(lineup)]
    vals=[]
    used_weights=[]
    for p,w in zip(lineup,weights):
        if not p.get("stats_available"):
            continue
        pa=max(int(p.get("pa",0) or 0),0)
        ops=shrink_mean(float(p.get("ops",LEAGUE_OPS)),pa,LEAGUE_OPS,100)
        vals.append(ops*w)
        used_weights.append(w)
    if not vals:
        return {"factor":1.0,"quality":0.45,"ops":LEAGUE_OPS}
    avg=sum(vals)/sum(used_weights)
    raw=clamp(avg/LEAGUE_OPS,.84,1.18)
    strength=1+(raw-1)*.42
    if not confirmed:
        strength=1+(strength-1)*.40
    quality=.95 if confirmed and len(vals)>=8 else .68 if len(vals)>=6 else .52
    return {"factor":clamp(strength,.93,1.08),"quality":quality,"ops":avg}

def project_f5_ensemble(offense,opposing_pitcher,lineup,lineup_confirmed,park_factor=1.0,weather=None):
    off=offense_components(offense)
    pit=pitcher_components(opposing_pitcher)
    lu=lineup_component(lineup,lineup_confirmed)
    park=clamp(park_factor,.93,1.10)
    wf=weather_factor(weather)

    lambdas=[
        BASE_F5*off["conservative"]*pit["conservative"]*park,
        BASE_F5*off["balanced"]*pit["balanced"]*lu["factor"]*park*wf,
        BASE_F5*off["recent"]*pit["skills"]*lu["factor"]*park*wf,
    ]
    lambdas=[clamp(x,.65,4.40) for x in lambdas]
    weights=np.array([.30,.45,.25])
    mean=float(np.average(lambdas,weights=weights))
    disagreement=float(np.std(lambdas))

    return mean,{
        "model_lambdas":[round(x,3) for x in lambdas],
        "model_disagreement":round(disagreement,3),
        "offense_season_reg":round(off["season_reg"],3),
        "offense_recent_reg":round(off["recent_reg"],3),
        "pitcher_era_reg":round(pit.get("era_reg",LEAGUE_ERA),3),
        "pitcher_k9_reg":round(pit.get("k9_reg",LEAGUE_K9),3),
        "lineup_ops_reg":round(lu["ops"],3),
        "lineup_factor":round(lu["factor"],3),
        "park_factor":round(park,3),
        "weather_factor":round(wf,3),
        "projected_runs":round(mean,3),
    }

def staff_proxy_factor(staff):
    if not staff:
        return 1.0
    era=shrink_mean(float(staff.get("era",LEAGUE_ERA)),80,LEAGUE_ERA,60)
    whip=shrink_mean(float(staff.get("whip",LEAGUE_WHIP)),80,LEAGUE_WHIP,60)
    recent=shrink_mean(float(staff.get("recent_ra_pg",LEAGUE_RPG)),10,LEAGUE_RPG,15)
    return clamp(.43*(era/LEAGUE_ERA)+.22*(whip/LEAGUE_WHIP)+.35*(recent/LEAGUE_RPG),.82,1.24)

def project_full_game_ensemble(away_f5,home_f5,away_form,home_form,away_staff,home_staff,park_factor=1.0,weather=None):
    park=clamp(park_factor,.93,1.10)
    wf=weather_factor(weather)
    ao=offense_components(away_form)
    ho=offense_components(home_form)
    home_bp=staff_proxy_factor(home_staff)
    away_bp=staff_proxy_factor(away_staff)

    away_rest=BASE_REST*ao["balanced"]*home_bp*park*wf
    home_rest=BASE_REST*ho["balanced"]*away_bp*park*wf

    away=clamp(away_f5+away_rest,1.5,9.2)
    home=clamp(home_f5+home_rest,1.5,9.2)

    return away,home,{
        "away_remaining":round(away_rest,3),
        "home_remaining":round(home_rest,3),
        "away_staff_factor":round(away_bp,3),
        "home_staff_factor":round(home_bp,3),
        "projected_total":round(away+home,3)
    }

def simulate_run_environment(away_lambda,home_lambda,quality,confirmed,seed,n=24000,full_game=False,model_disagreement=0.0):
    rng=np.random.default_rng(seed)

    # Parameter uncertainty is explicitly simulated by drawing the latent run rate.
    # Lower quality / missing lineups = wider parameter distribution.
    base_cv=.10 if confirmed else .16
    if full_game:
        base_cv+=.035
    base_cv+=clamp(model_disagreement/3,.0,.05)
    base_cv+=clamp((80-quality)/500,0,.06)
    base_cv=clamp(base_cv,.08,.25)

    def gamma_poisson(mu):
        shape=1/(base_cv**2)
        scale=mu/shape
        latent=rng.gamma(shape,scale,size=n)
        return rng.poisson(latent)

    away=gamma_poisson(away_lambda)
    home=gamma_poisson(home_lambda)
    total=away+home
    return {"away":away,"home":home,"total":total,"cv":base_cv}

def sim_total_prob(sim,line,direction):
    arr=sim["total"]
    if direction=="over":
        return float(np.mean(arr>line))
    return float(np.mean(arr<line))

def sim_ml_prob(sim,side):
    a=sim["away"];h=sim["home"]
    non_tie=a!=h
    if not np.any(non_tie):
        return .5
    if side=="away":
        return float(np.mean(a[non_tie]>h[non_tie]))
    return float(np.mean(h[non_tie]>a[non_tie]))

def scenario_total_probs(lambdas_away,lambdas_home,line,direction):
    probs=[]
    for a,h in zip(lambdas_away,lambdas_home):
        lam=max(a+h,.05)
        # deterministic Poisson scenario used only to measure model disagreement.
        maxk=35
        pmf=[math.exp(-lam)*(lam**k)/math.factorial(k) for k in range(maxk)]
        if direction=="over":
            p=sum(pmf[k] for k in range(maxk) if k>line)
        else:
            p=sum(pmf[k] for k in range(maxk) if k<line)
        probs.append(clamp(p,0,1))
    return probs

def conservative_probability(center,scenario_probs,quality,confirmed,volatility):
    if scenario_probs:
        low=min(scenario_probs)
        high=max(scenario_probs)
        agreement=1-(high-low)
    else:
        low=high=center
        agreement=1.0

    # Conservative displayed probability: shrink toward 50% according to uncertainty.
    shrink=.97
    if not confirmed: shrink-=.08
    if quality<80: shrink-=min(.10,(80-quality)/200)
    if volatility=="high": shrink-=.08
    elif volatility=="medium": shrink-=.03
    shrink=clamp(shrink,.72,.97)
    adjusted=.5+(center-.5)*shrink

    lo=clamp(min(low,adjusted)-(.025 if not confirmed else .012),.01,.99)
    hi=clamp(max(high,adjusted)+.025,.01,.99)
    return adjusted,lo,hi,clamp(agreement,0,1)

def beta_binomial_event_prob(rate,pa,threshold,prior_rate,prior_strength,sample_n):
    # Bayesian shrinkage of the underlying per-PA event rate.
    shr=shrink_mean(rate,sample_n,prior_rate,prior_strength)
    n=max(1,int(round(pa)))
    # Binomial event distribution is more appropriate than Poisson for PA-level yes/no events.
    p=0.0
    for k in range(threshold,n+1):
        p += math.comb(n,k)*(shr**k)*((1-shr)**(n-k))
    return clamp(p,0,1),shr,n

def expected_pa(order):
    return {1:4.55,2:4.50,3:4.45,4:4.35,5:4.25,6:4.10,7:4.00,8:3.90,9:3.80}.get(order,4.10)

def build_prop_candidates_v5(away_pitcher,home_pitcher,away_pitcher_name,home_pitcher_name,
                             away_lineup,home_lineup,lineups_confirmed=False):
    props=[]

    for name,p,opp_lineup in [
        (away_pitcher_name,away_pitcher,home_lineup),
        (home_pitcher_name,home_pitcher,away_lineup),
    ]:
        if p:
            ip=max(float(p.get("innings",0) or 0),0)
            k9_reg=shrink_mean(float(p.get("k9",LEAGUE_K9)),ip,LEAGUE_K9,50)
            exp_ip=shrink_mean(float(p.get("expected_ip",5.2)),max(p.get("games_started",0),1),5.2,7)

            opp_rates=[x.get("k_rate") for x in opp_lineup if x.get("stats_available") and x.get("k_rate") is not None]
            if opp_rates:
                # Each batter rate already season based; regress team lineup K% toward league.
                raw_opp=float(np.mean(opp_rates))
                opp_k=shrink_mean(raw_opp,len(opp_rates)*70,LEAGUE_K_PA,300)
            else:
                opp_k=LEAGUE_K_PA

            matchup=clamp(opp_k/LEAGUE_K_PA,.88,1.13)
            mean_k=clamp(k9_reg*exp_ip/9*matchup,1.5,9.5)

            # Negative-binomial-like uncertainty via gamma-Poisson mixture.
            seed=stable_seed(name,"K")
            rng=np.random.default_rng(seed)
            cv=.16 if opp_lineup else .20
            shape=1/(cv**2)
            latent=rng.gamma(shape,mean_k/shape,size=18000)
            ks=rng.poisson(latent)

            for th in [4,5,6,7]:
                center=float(np.mean(ks>=th))
                q=84 if opp_lineup else 76
                confirmed=True
                # Range represents plausible parameter uncertainty, not MC sampling error.
                lo=clamp(center-.055 if opp_lineup else center-.08,.01,.99)
                hi=clamp(center+.055 if opp_lineup else center+.08,.01,.99)
                props.append({
                    "category":"Pitcher Ks",
                    "label":f"{name} {th}+ ponches",
                    "prob":center,"prob_low":lo,"prob_high":hi,
                    "agreement":.88 if opp_lineup else .76,
                    "quality":q,"confirmed":confirmed,"volatility":"medium",
                    "reason":f"K/9 regresado {k9_reg:.2f}; IP esperadas {exp_ip:.1f}; K% rival ajustado {opp_k*100:.1f}%; media ~{mean_k:.1f} K."
                })

    def add_hitters(lineup):
        for p in lineup[:9]:
            if not p.get("stats_available"):
                continue
            pa=expected_pa(p["order"])
            sample=max(int(p.get("pa",0) or 0),0)
            confirmed=lineups_confirmed
            q=88 if confirmed else 64
            split_adj=clamp(float(p.get("ops",LEAGUE_OPS))/LEAGUE_OPS,.88,1.12)

            hit_rate=clamp(float(p.get("hit_rate",LEAGUE_HIT_PA))*split_adj,0,.60)
            p1,shr_hit,npa=beta_binomial_event_prob(hit_rate,pa,1,LEAGUE_HIT_PA,120,sample)
            p2,_,_=beta_binomial_event_prob(hit_rate,pa,2,LEAGUE_HIT_PA,120,sample)

            tb_rate=clamp(float(p.get("tb_rate",LEAGUE_TB_PA))*split_adj,0,.90)
            # TB is not Bernoulli; approximate 1+ TB using probability of a hit-like TB event,
            # and 2+ with a conservative compound-event approximation.
            ptb1,shr_tb,_=beta_binomial_event_prob(min(tb_rate,.70),pa,1,LEAGUE_TB_PA,130,sample)
            ptb2=clamp(ptb1*(.42+.28*clamp(shr_tb/LEAGUE_TB_PA,.7,1.4)),.05,.82)

            hr_rate=clamp(float(p.get("hr_rate",LEAGUE_HR_PA))*split_adj,0,.18)
            phr,shr_hr,_=beta_binomial_event_prob(hr_rate,pa,1,LEAGUE_HR_PA,180,sample)

            def rng_band(center,vol):
                width=.045 if confirmed else .075
                if vol=="high": width+=.055
                return clamp(center-width,.01,.99),clamp(center+width,.01,.99)

            for label,prob,vol,detail in [
                (f"{p['name']} 1+ hit",p1,"low",f"Hit/PA regresado {shr_hit:.3f}; ~{pa:.1f} PA; turno #{p['order']}."),
                (f"{p['name']} 2+ hits",p2,"medium",f"Hit/PA regresado {shr_hit:.3f}; ~{pa:.1f} PA; turno #{p['order']}."),
                (f"{p['name']} 1+ base total",ptb1,"low",f"TB/PA regresado {shr_tb:.3f}; ~{pa:.1f} PA; turno #{p['order']}."),
                (f"{p['name']} 2+ bases totales",ptb2,"medium",f"TB/PA regresado {shr_tb:.3f}; ~{pa:.1f} PA; turno #{p['order']}."),
                (f"{p['name']} 1+ HR",phr,"high",f"HR/PA regresado {shr_hr:.3f}; mercado de alta varianza."),
            ]:
                lo,hi=rng_band(prob,vol)
                props.append({
                    "category":"Home Run" if "HR" in label else "Hits" if "hit" in label else "Total Bases",
                    "label":label,"prob":prob,"prob_low":lo,"prob_high":hi,
                    "agreement":.90 if confirmed else .72,
                    "quality":q if vol!="high" else max(55,q-12),
                    "confirmed":confirmed,"volatility":vol,"reason":detail
                })

    add_hitters(away_lineup)
    add_hitters(home_lineup)
    return props

def confidence_score(item):
    p=item["prob"]
    low=item.get("prob_low",p)
    high=item.get("prob_high",p)
    q=item.get("quality",65)/100
    agreement=item.get("agreement",.75)
    confirmed=1.0 if item.get("confirmed",False) else .72
    volatility=item.get("volatility","medium")
    width=high-low
    stability=clamp(1-width/.30,0,1)
    prob_strength=clamp((low-.50)/.25,0,1)

    vol_mult={"low":1.0,"medium":.92,"high":.76}.get(volatility,.90)
    score=100*(.36*prob_strength+.24*q+.22*agreement+.18*stability)*confirmed*vol_mult
    return int(round(clamp(score,0,99)))

def rank_automatic_candidates_v5(items,max_items=5):
    ranked=[]
    for item in items:
        x=dict(item)
        x["confidence_score"]=confidence_score(x)
        # Use the conservative lower bound as the admission filter.
        if x.get("prob_low",x["prob"]) < .54:
            continue
        if x["confidence_score"] < 48:
            continue
        ranked.append(x)

    ranked=sorted(
        ranked,
        key=lambda x:(x["confidence_score"],x.get("prob_low",x["prob"]),x["prob"]),
        reverse=True
    )

    # Diversity: at most 2 from same player/base market prefix and at most 2 from same category.
    selected=[]
    prefix_counts={}
    cat_counts={}
    for item in ranked:
        label=item["label"]
        prefix=label
        for token in [" 1+"," 2+"," 3+"," 4+"," 5+"," 6+"," 7+"," Over "," Under "]:
            if token in prefix:
                prefix=prefix.split(token)[0]
                break
        if prefix_counts.get(prefix,0)>=2:
            continue
        if cat_counts.get(item["category"],0)>=2:
            continue
        selected.append(item)
        prefix_counts[prefix]=prefix_counts.get(prefix,0)+1
        cat_counts[item["category"]]=cat_counts.get(item["category"],0)+1
        if len(selected)>=max_items:
            break
    return selected

def evaluate_selected_candidate_v5(item,odds):
    # For price decisions, use central probability but penalize uncertainty.
    p=item["prob"]
    p_cons=item.get("prob_low",p)
    fair=prob_to_decimal(p)
    fair_conservative=prob_to_decimal(p_cons)
    ev=p*odds-1
    conservative_ev=p_cons*odds-1
    target=(1.05/max(p_cons,.01))

    if conservative_ev>=.06 and odds>=target and item.get("confidence_score",0)>=60:
        verdict="APOSTAR"
    elif conservative_ev>=.015 and odds>=fair_conservative:
        verdict="LEAN"
    else:
        verdict="PASS"

    score=conservative_ev*(item.get("confidence_score",50)/100)
    return {
        "ev":ev,
        "conservative_ev":conservative_ev,
        "fair_odds":fair,
        "fair_conservative":fair_conservative,
        "target_odds":target,
        "verdict":verdict,
        "score":score
    }


# ================= APP UI =================
st.set_page_config(page_title="MLB Betting Hub V5", page_icon="⚾", layout="wide")
st_autorefresh(interval=120000, key="v5_refresh")

st.title("⚾ MLB Betting Hub — V5")
st.caption("Motor estadístico mejorado: regresión a la media + ensemble + simulación + incertidumbre.")

c1,c2=st.columns([1,2])
with c1:
    selected_date=st.date_input("📅 Fecha",value=date.today())

games=get_schedule(selected_date.isoformat())
if not games:
    st.warning("No encontré partidos MLB para esta fecha o MLB no respondió.")
    st.stop()

with c2:
    game_label=st.selectbox("⚾ Partido",[g["label"] for g in games])

game=next(g for g in games if g["label"]==game_label)

game_state_key=f"{selected_date.isoformat()}-{game['game_pk']}"
if st.session_state.get("v5_game_key")!=game_state_key:
    st.session_state["v5_game_key"]=game_state_key
    st.session_state["v5_analysis_ready"]=False

with st.spinner("Consultando MLB, contexto y lineups..."):
    away_form=get_team_form(game["away_id"],selected_date.isoformat())
    home_form=get_team_form(game["home_id"],selected_date.isoformat())
    away_pitch=get_pitcher_stats(game["away_pitcher_id"],selected_date.year) if game["away_pitcher_id"] else None
    home_pitch=get_pitcher_stats(game["home_pitcher_id"],selected_date.year) if game["home_pitcher_id"] else None
    away_staff=get_team_pitching_profile(game["away_id"],selected_date.year,selected_date.isoformat())
    home_staff=get_team_pitching_profile(game["home_id"],selected_date.year,selected_date.isoformat())

    park=get_stadium_context(game["home_abbr"])
    weather=get_weather(park["lat"],park["lon"],selected_date.isoformat(),game.get("game_time_local")) if park else None

    raw_lineups=get_lineups(game["game_pk"])
    away_lineup=enrich_lineup(raw_lineups.get("away",[]),selected_date.year,(home_pitch or {}).get("hand","R"))
    home_lineup=enrich_lineup(raw_lineups.get("home",[]),selected_date.year,(away_pitch or {}).get("hand","R"))

away_confirmed=len(away_lineup)>=9
home_confirmed=len(home_lineup)>=9
both_confirmed=away_confirmed and home_confirmed

quality=100
quality_notes=[]
if not game["away_pitcher_id"] or not game["home_pitcher_id"]:
    quality-=18;quality_notes.append("⚠️ Falta al menos un abridor confirmado")
else: quality_notes.append("✅ Abridores confirmados")
if not away_confirmed:
    quality-=12;quality_notes.append(f"⚠️ Lineup {game['away_abbr']} pendiente")
else: quality_notes.append(f"✅ Lineup {game['away_abbr']} confirmado")
if not home_confirmed:
    quality-=12;quality_notes.append(f"⚠️ Lineup {game['home_abbr']} pendiente")
else: quality_notes.append(f"✅ Lineup {game['home_abbr']} confirmado")
if weather is None:
    quality-=8;quality_notes.append("⚠️ Clima no disponible")
else: quality_notes.append("✅ Clima disponible")
if away_staff is None or home_staff is None:
    quality-=8;quality_notes.append("⚠️ Bullpen proxy incompleto")
else: quality_notes.append("✅ Bullpen/staff proxy disponible")
quality=max(30,min(100,quality))

park_factor=(park or {}).get("factor",1.0)

away_f5,away_f5_debug=project_f5_ensemble(away_form,home_pitch,away_lineup,away_confirmed,park_factor,weather)
home_f5,home_f5_debug=project_f5_ensemble(home_form,away_pitch,home_lineup,home_confirmed,park_factor,weather)
f5_total=away_f5+home_f5

away_fg,home_fg,fg_debug=project_full_game_ensemble(
    away_f5,home_f5,away_form,home_form,away_staff,home_staff,park_factor,weather
)
fg_total=away_fg+home_fg

# Monte Carlo predictive distributions.
f5_disagreement=away_f5_debug["model_disagreement"]+home_f5_debug["model_disagreement"]
f5_sim=simulate_run_environment(
    away_f5,home_f5,quality,both_confirmed,
    stable_seed(game["game_pk"],selected_date.isoformat(),"F5"),
    n=24000,full_game=False,model_disagreement=f5_disagreement
)
fg_sim=simulate_run_environment(
    away_fg,home_fg,max(35,quality-10),False,
    stable_seed(game["game_pk"],selected_date.isoformat(),"FG"),
    n=24000,full_game=True,model_disagreement=f5_disagreement
)

props=build_prop_candidates_v5(
    away_pitch,home_pitch,game["away_pitcher_name"],game["home_pitcher_name"],
    away_lineup,home_lineup,both_confirmed
)

# =========================
# Contexto visible
# =========================
st.divider()
st.subheader("📋 Contexto del partido")

ctx1,ctx2,ctx3=st.columns([1,1,1.1])
with ctx1:
    st.markdown(f"### ✈️ {game['away_abbr']}")
    st.write(f"**Pitcher:** {game['away_pitcher_name']}")
    if away_pitch:
        st.caption(
            f"{away_pitch['hand']}HP · ERA {away_pitch['era']:.2f} · WHIP {away_pitch['whip']:.2f} · "
            f"K/9 {away_pitch['k9']:.2f} · BB/9 {away_pitch['bb9']:.2f} · HR/9 {away_pitch['hr9']:.2f}"
        )
    st.caption(f"Ofensiva {away_form['season_rpg']:.2f} R/G · últimos 15 {away_form['recent_rpg']:.2f}")

with ctx2:
    st.markdown(f"### 🏠 {game['home_abbr']}")
    st.write(f"**Pitcher:** {game['home_pitcher_name']}")
    if home_pitch:
        st.caption(
            f"{home_pitch['hand']}HP · ERA {home_pitch['era']:.2f} · WHIP {home_pitch['whip']:.2f} · "
            f"K/9 {home_pitch['k9']:.2f} · BB/9 {home_pitch['bb9']:.2f} · HR/9 {home_pitch['hr9']:.2f}"
        )
    st.caption(f"Ofensiva {home_form['season_rpg']:.2f} R/G · últimos 15 {home_form['recent_rpg']:.2f}")

with ctx3:
    st.markdown("### 🏟️ Estadio y clima")
    st.write(f"**{(park or {}).get('name','N/D')}**")
    st.caption(f"Park factor {(park or {}).get('factor',1.0):.2f}")
    if weather:
        st.caption(
            f"🌡️ {weather['temp_f']:.0f}°F · 💨 {weather['wind_mph']:.0f} mph · "
            f"💧 {weather['humidity']:.0f}% · 🌧️ {weather.get('precip_probability',0):.0f}%"
        )
    else: st.caption("Clima: N/D")
    st.caption(f"Lineups: {game['away_abbr']} {'✅' if away_confirmed else '⚠️'} · {game['home_abbr']} {'✅' if home_confirmed else '⚠️'}")

st.markdown("### 👥 Lineups")
lu1,lu2=st.columns(2)
with lu1:
    st.write(f"**{game['away_abbr']} — {'CONFIRMADO ✅' if away_confirmed else 'PENDIENTE ⚠️'}**")
    if away_lineup:
        for p in away_lineup[:9]:
            src="split" if p.get("used_split") else "temporada"
            st.caption(f"{p['order']}. {p['name']} · OPS {p['ops']:.3f} ({src})")
    else: st.caption("MLB todavía no publicó el orden al bat.")
with lu2:
    st.write(f"**{game['home_abbr']} — {'CONFIRMADO ✅' if home_confirmed else 'PENDIENTE ⚠️'}**")
    if home_lineup:
        for p in home_lineup[:9]:
            src="split" if p.get("used_split") else "temporada"
            st.caption(f"{p['order']}. {p['name']} · OPS {p['ops']:.3f} ({src})")
    else: st.caption("MLB todavía no publicó el orden al bat.")

st.caption(
    f"Última consulta: {datetime.now().strftime('%H:%M:%S')} · Calidad de datos {quality}/100 · "
    "refresco automático aproximado cada 2 minutos."
)

b1,b2,sp=st.columns([1,1,2.2])
with b1:
    update_now=st.button("🔄 Actualizar datos",use_container_width=True,type="secondary")
with b2:
    analyze_now=st.button("🧠 Analizar partido",use_container_width=True,type="primary")

if update_now:
    st.cache_data.clear()
    st.session_state["v5_analysis_ready"]=False
    st.rerun()
if analyze_now:
    st.session_state["v5_analysis_ready"]=True

# =========================
# Construcción automática
# =========================
automatic=[]

away_models=away_f5_debug["model_lambdas"]
home_models=home_f5_debug["model_lambdas"]

for line in [3.5,4.5,5.5,6.5]:
    for direction,label_dir in [("over","Over"),("under","Under")]:
        center=sim_total_prob(f5_sim,line,direction)
        scenario=scenario_total_probs(away_models,home_models,line,direction)
        p,lo,hi,agreement=conservative_probability(center,scenario,quality,both_confirmed,"medium")
        automatic.append({
            "category":"F5","label":f"F5 {label_dir} {line:g}",
            "prob":p,"prob_low":lo,"prob_high":hi,"agreement":agreement,
            "quality":quality,"confirmed":both_confirmed,"volatility":"medium",
            "reason":f"Monte Carlo 24k · total F5 central {f5_total:.2f} · modelos {', '.join(f'{x+y:.2f}' for x,y in zip(away_models,home_models))}."
        })

for side,abbr in [("away",game["away_abbr"]),("home",game["home_abbr"])]:
    center=sim_ml_prob(f5_sim,side)
    # Approximate scenario ML by run differential logistic transformation.
    scenario=[]
    for a,h in zip(away_models,home_models):
        d=(a-h) if side=="away" else (h-a)
        scenario.append(1/(1+math.exp(-0.78*d)))
    p,lo,hi,agreement=conservative_probability(center,scenario,quality,both_confirmed,"medium")
    automatic.append({
        "category":"F5","label":f"{abbr} F5 ML",
        "prob":p,"prob_low":lo,"prob_high":hi,"agreement":agreement,
        "quality":quality,"confirmed":both_confirmed,"volatility":"medium",
        "reason":f"Monte Carlo 24k · proyección F5 {game['away_abbr']} {away_f5:.2f} - {game['home_abbr']} {home_f5:.2f}."
    })

for line in [7.5,8.5,9.5,10.5]:
    for direction,label_dir in [("over","Over"),("under","Under")]:
        center=sim_total_prob(fg_sim,line,direction)
        # Full-game model disagreement gets a wider range because bullpen remains proxy-based.
        pseudo=[clamp(center-.05,0,1),center,clamp(center+.05,0,1)]
        p,lo,hi,agreement=conservative_probability(center,pseudo,max(35,quality-10),False,"medium")
        automatic.append({
            "category":"Full Game BETA","label":f"Full Game {label_dir} {line:g}",
            "prob":p,"prob_low":lo,"prob_high":hi,"agreement":agreement*.88,
            "quality":max(35,quality-10),"confirmed":False,"volatility":"medium",
            "reason":f"Monte Carlo 24k · total completo central {fg_total:.2f} · bullpen/staff todavía proxy."
        })

for side,abbr in [("away",game["away_abbr"]),("home",game["home_abbr"])]:
    center=sim_ml_prob(fg_sim,side)
    pseudo=[clamp(center-.055,0,1),center,clamp(center+.055,0,1)]
    p,lo,hi,agreement=conservative_probability(center,pseudo,max(35,quality-10),False,"medium")
    automatic.append({
        "category":"Full Game BETA","label":f"{abbr} ML Full Game",
        "prob":p,"prob_low":lo,"prob_high":hi,"agreement":agreement*.88,
        "quality":max(35,quality-10),"confirmed":False,"volatility":"medium",
        "reason":f"Monte Carlo 24k · proyección {game['away_abbr']} {away_fg:.2f} - {game['home_abbr']} {home_fg:.2f}."
    })

automatic.extend(props)
ranked_auto=rank_automatic_candidates_v5(automatic,max_items=5)

# =========================
# Pantallas
# =========================
tab1,tab2=st.tabs(["1️⃣ Qué buscar","2️⃣ Evaluar momios"])

with tab1:
    st.subheader(f"🧠 Análisis estadístico {game['away_abbr']} @ {game['home_abbr']}")
    q1,q2,q3=st.columns([1,1,1.4])
    q1.metric("Calidad de datos",f"{quality}/100")
    q2.metric("Lineups","✅ Confirmados" if both_confirmed else "⚠️ Provisional")
    q3.caption("V5 no ordena solo por %: usa probabilidad conservadora, acuerdo de modelos, incertidumbre y calidad.")

    if not both_confirmed:
        st.warning("Faltan lineups. V5 amplía automáticamente la incertidumbre y reduce la confianza de props/bateadores.")

    if not st.session_state.get("v5_analysis_ready",False):
        st.info("👆 Revisa el contexto y pulsa **🧠 Analizar partido**.")
    elif not ranked_auto:
        st.info("⚪ PASS ESTADÍSTICO — No encontré suficientes opciones robustas. V5 no fuerza cinco picks.")
    else:
        st.markdown("### 🏆 Oportunidades más robustas")
        for i,item in enumerate(ranked_auto,1):
            sc=item["confidence_score"]
            icon="🟢" if sc>=72 else "🟡" if sc>=58 else "⚪"
            state="CONFIRMADO" if item.get("confirmed") else "PROVISIONAL"
            st.markdown(
                f"**{i}. {icon} {item['label']}**  \n"
                f"Prob. central **{item['prob']*100:.1f}%** · "
                f"Rango **{item['prob_low']*100:.1f}–{item['prob_high']*100:.1f}%** · "
                f"Confianza **{sc}/100** · "
                f"Acuerdo **{item.get('agreement',0)*100:.0f}%** · {state}"
            )
            st.caption(item["reason"])

    with st.expander("🔬 Ver modelo y simulación",expanded=False):
        a,b,c=st.columns(3)
        a.metric(f"{game['away_abbr']} F5",f"{away_f5:.2f}")
        b.metric(f"{game['home_abbr']} F5",f"{home_f5:.2f}")
        c.metric("Total F5",f"{f5_total:.2f}")
        a,b,c=st.columns(3)
        a.metric(f"{game['away_abbr']} Full",f"{away_fg:.2f}")
        b.metric(f"{game['home_abbr']} Full",f"{home_fg:.2f}")
        c.metric("Total Full",f"{fg_total:.2f}")

        st.write("**Submodelos F5 (carreras esperadas)**")
        st.write({
            game["away_abbr"]:away_f5_debug["model_lambdas"],
            game["home_abbr"]:home_f5_debug["model_lambdas"],
            "CV simulación F5":round(f5_sim["cv"],3),
            "CV simulación Full":round(fg_sim["cv"],3),
        })

        st.write("**Qué hace V5 diferente**")
        st.write("• Regresa muestras pequeñas hacia la media MLB.")
        st.write("• Mezcla modelo conservador, balanceado y sensible a forma reciente.")
        st.write("• Simula incertidumbre del parámetro de carreras, no solo resultados Poisson fijos.")
        st.write("• Penaliza falta de lineup, mercados volátiles y desacuerdo entre modelos.")
        st.write("• Props de hits usan aproximación binomial con tasa regresada; Ks usan mezcla gamma-Poisson.")

        st.write("**Datos disponibles**")
        for note in quality_notes:
            st.write(note)

with tab2:
    st.subheader("💰 ¿El precio de Draftea compensa el riesgo?")
    st.caption("Las 5 recomendaciones aparecen seleccionadas. Quita cualquiera que Draftea no tenga.")

    if not st.session_state.get("v5_analysis_ready",False):
        st.info("Primero pulsa **🧠 Analizar partido**.")
    elif not ranked_auto:
        st.info("No hay recomendaciones robustas que evaluar.")
    else:
        labels=[x["label"] for x in ranked_auto]
        selected=st.multiselect("¿Cuáles encontraste en Draftea?",labels,default=labels)

        evaluated=[]
        for idx,label in enumerate(selected):
            item=next(x for x in ranked_auto if x["label"]==label)
            target=1.05/max(item["prob_low"],.01)
            c1,c2,c3=st.columns([2.2,1,1])
            c1.write(f"**{label}**")
            c2.caption(f"Cuota objetivo ≥ {target:.2f}x")
            odds=c3.number_input(
                f"Momio {idx+1}",1.01,100.0,1.80,.01,
                format="%.2f",key=f"odd_v5_{idx}"
            )
            res=evaluate_selected_candidate_v5(item,odds)
            evaluated.append({**item,**res,"odds":odds})

        if evaluated:
            evaluated=sorted(evaluated,key=lambda x:x["score"],reverse=True)
            st.markdown("### Resultado")
            best=evaluated[0]
            if best["verdict"]=="APOSTAR":
                st.success(f"🟢 MEJOR PRECIO: {best['label']} @ {best['odds']:.2f}x")
            elif best["verdict"]=="LEAN":
                st.warning(f"🟡 MEJOR PRECIO: {best['label']} @ {best['odds']:.2f}x")
            else:
                st.info("⚪ PASS GENERAL — El precio no compensa la incertidumbre del modelo.")

            for i,x in enumerate(evaluated,1):
                icon="🟢" if x["verdict"]=="APOSTAR" else "🟡" if x["verdict"]=="LEAN" else "⚪"
                st.write(
                    f"**{i}. {icon} {x['label']} @ {x['odds']:.2f}x** — "
                    f"Central {x['prob']*100:.1f}% | Conservadora {x['prob_low']*100:.1f}% | "
                    f"EV central {x['ev']*100:+.1f}% | EV conservador {x['conservative_ev']*100:+.1f}% | "
                    f"{x['verdict']}"
                )

st.divider()
st.caption(
    "V5 experimental. La probabilidad mostrada no es una garantía. "
    "La calibración histórica/backtesting sigue siendo necesaria antes de considerar estas probabilidades validadas."
)
