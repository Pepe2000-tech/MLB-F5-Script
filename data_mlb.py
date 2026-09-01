from datetime import datetime, timedelta
import requests
import streamlit as st

BASE="https://statsapi.mlb.com/api/v1"
HEADERS={"User-Agent":"MLB-Betting-Hub/4.0"}

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
    # Proxy de bullpen/staff: estadísticas de pitcheo del equipo + carreras permitidas recientes.
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
