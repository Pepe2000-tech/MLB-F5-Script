from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import math
import hashlib
import csv
import io
import re
import json
import os
import itertools
import requests
import numpy as np
import streamlit as st

# ================= DATA LAYER =================
BASE="https://statsapi.mlb.com/api/v1"
HEADERS={"User-Agent":"MLB-Betting-Hub/7.2.1"}
CDMX_TZ=ZoneInfo("America/Mexico_City")

def now_cdmx():
    """Return the current timezone-aware datetime in Mexico City."""
    return datetime.now(CDMX_TZ)


# ================= V7 PERSISTENCIA OPCIONAL =================
def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

LOCAL_PAPER_STORE=os.getenv("MLB_PAPER_STORE","/tmp/mlb_betting_hub_v72_paper_bets.json")

def persistent_store_enabled():
    return bool(_secret("SUPABASE_URL") and _secret("SUPABASE_KEY"))

def _local_load_paper_bets():
    try:
        if not os.path.exists(LOCAL_PAPER_STORE): return []
        with open(LOCAL_PAPER_STORE,"r",encoding="utf-8") as f:
            rows=json.load(f)
        return rows if isinstance(rows,list) else []
    except Exception:
        return []

def _local_write_paper_bets(rows):
    try:
        tmp=LOCAL_PAPER_STORE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(rows,f,ensure_ascii=False,default=str)
        os.replace(tmp,LOCAL_PAPER_STORE)
        return True
    except Exception:
        return False

def _supabase_headers(prefer=False):
    key=_secret("SUPABASE_KEY")
    h={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"}
    if prefer:
        h["Prefer"]="resolution=merge-duplicates,return=minimal"
    return h

def persistent_load_paper_bets():
    if not persistent_store_enabled():
        return _local_load_paper_bets()
    try:
        url=_secret("SUPABASE_URL").rstrip("/")+"/rest/v1/mlb_paper_bets"
        r=requests.get(url,params={"select":"payload","order":"created_at.asc"},headers=_supabase_headers(),timeout=12)
        r.raise_for_status()
        rows=[x.get("payload",{}) for x in r.json() if isinstance(x.get("payload"),dict)]
        _local_write_paper_bets(rows)
        return rows
    except Exception:
        return _local_load_paper_bets()

def persistent_upsert_paper_bet(record):
    # Always persist locally first so F5/reruns do not erase the ticket on the same Streamlit instance.
    rows=_local_load_paper_bets()
    pid=str(record.get("paper_id"))
    replaced=False
    for i,row in enumerate(rows):
        if str(row.get("paper_id"))==pid:
            rows[i]=record; replaced=True; break
    if not replaced: rows.append(record)
    local_ok=_local_write_paper_bets(rows)
    if not persistent_store_enabled():
        return local_ok
    try:
        url=_secret("SUPABASE_URL").rstrip("/")+"/rest/v1/mlb_paper_bets"
        payload={
            "paper_id":pid,
            "created_at":record.get("freeze_time_iso") or now_cdmx().isoformat(),
            "payload":record,
        }
        r=requests.post(url,params={"on_conflict":"paper_id"},headers=_supabase_headers(True),json=payload,timeout=12)
        r.raise_for_status()
        return True
    except Exception:
        return local_ok

def persistent_delete_all_paper_bets():
    local_ok=_local_write_paper_bets([])
    if not persistent_store_enabled(): return local_ok
    try:
        url=_secret("SUPABASE_URL").rstrip("/")+"/rest/v1/mlb_paper_bets"
        r=requests.delete(url,params={"paper_id":"not.is.null"},headers=_supabase_headers(True),timeout=12)
        r.raise_for_status()
        return True
    except Exception:
        return local_ok


# ================= V7 MOMIOS DE REFERENCIA =================
ODDS_API_BASE="https://api.the-odds-api.com/v4"

ODDS_TEAM_ABBR={
    "Arizona Diamondbacks":"ARI","Atlanta Braves":"ATL","Baltimore Orioles":"BAL","Boston Red Sox":"BOS",
    "Chicago Cubs":"CHC","Chicago White Sox":"CWS","Cincinnati Reds":"CIN","Cleveland Guardians":"CLE",
    "Colorado Rockies":"COL","Detroit Tigers":"DET","Houston Astros":"HOU","Kansas City Royals":"KC",
    "Los Angeles Angels":"LAA","Los Angeles Dodgers":"LAD","Miami Marlins":"MIA","Milwaukee Brewers":"MIL",
    "Minnesota Twins":"MIN","New York Mets":"NYM","New York Yankees":"NYY","Athletics":"ATH",
    "Oakland Athletics":"ATH","Philadelphia Phillies":"PHI","Pittsburgh Pirates":"PIT","San Diego Padres":"SD",
    "San Francisco Giants":"SF","Seattle Mariners":"SEA","St. Louis Cardinals":"STL","Tampa Bay Rays":"TB",
    "Texas Rangers":"TEX","Toronto Blue Jays":"TOR","Washington Nationals":"WSH"
}

def odds_api_enabled():
    return bool(_secret("ODDS_API_KEY"))

def _odds_norm_name(x):
    return re.sub(r"[^a-z0-9]","",str(x or "").lower())

def _odds_market_key(item):
    fam=item.get("market_family")
    return {
        "f5_total":"alternate_totals_1st_5_innings",
        "fg_total":"totals",
        "pitcher_k":"pitcher_strikeouts",
        "hits":"batter_hits",
        "total_bases":"batter_total_bases",
        "hrr":"batter_hits_runs_rbis",
        "home_run":"batter_home_runs",
    }.get(fam)

@st.cache_data(ttl=300,show_spinner=False)
def odds_api_events():
    if not odds_api_enabled(): return [],{}
    try:
        r=requests.get(f"{ODDS_API_BASE}/sports/baseball_mlb/events",params={"apiKey":_secret("ODDS_API_KEY"),"dateFormat":"iso"},timeout=12)
        r.raise_for_status()
        usage={"remaining":r.headers.get("x-requests-remaining"),"used":r.headers.get("x-requests-used"),"last":r.headers.get("x-requests-last")}
        return r.json(),usage
    except Exception as e:
        return [],{"error":str(e)}

def odds_event_for_game(g,events=None):
    if events is None: events,_=odds_api_events()
    ga,gh=g.get("away_abbr"),g.get("home_abbr")
    exact=[]
    for ev in events:
        ea=ODDS_TEAM_ABBR.get(ev.get("away_team")); eh=ODDS_TEAM_ABBR.get(ev.get("home_team"))
        if ea==ga and eh==gh: exact.append(ev)
    if not exact:return None
    # Dobles carteleras: elegir el horario más cercano al de MLB.
    try:
        gt=datetime.fromisoformat(str(g.get("game_time_local")).replace("Z","+00:00"))
        return min(exact,key=lambda e:abs((datetime.fromisoformat(e["commence_time"].replace("Z","+00:00"))-gt).total_seconds()))
    except Exception:
        return exact[0]

@st.cache_data(ttl=300,show_spinner=False)
def odds_api_event_odds(event_id,markets_csv,region="us"):
    if not odds_api_enabled() or not event_id or not markets_csv:return None,{}
    try:
        r=requests.get(
            f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds",
            params={"apiKey":_secret("ODDS_API_KEY"),"regions":region,"markets":markets_csv,"oddsFormat":"decimal","dateFormat":"iso"},
            timeout=15
        )
        r.raise_for_status()
        usage={"remaining":r.headers.get("x-requests-remaining"),"used":r.headers.get("x-requests-used"),"last":r.headers.get("x-requests-last")}
        return r.json(),usage
    except Exception as e:
        return None,{"error":str(e)}

def _all_outcomes(event_odds,market_key):
    rows=[]
    if not event_odds:return rows
    for book in event_odds.get("bookmakers",[]):
        for market in book.get("markets",[]):
            if market.get("key")!=market_key:continue
            for out in market.get("outcomes",[]):
                try: price=float(out.get("price"))
                except Exception: continue
                rows.append({
                    "book":book.get("title",book.get("key","Book")),"book_key":book.get("key"),
                    "last_update":market.get("last_update") or book.get("last_update"),
                    "name":str(out.get("name","")).lower(),"description":out.get("description"),
                    "point":out.get("point"),"price":price,
                })
    return rows

def reference_quote_from_event(item,event_odds):
    mk=_odds_market_key(item)
    if not mk:return None
    rows=_all_outcomes(event_odds,mk)
    if not rows:return None
    side=str(item.get("side","")).lower(); subject=_odds_norm_name(item.get("subject"))
    target_line=float(item.get("line",0) or 0)
    filt=[]
    for r in rows:
        if side and r["name"]!=side:continue
        if subject and item.get("market_family") not in ("f5_total","fg_total"):
            if _odds_norm_name(r.get("description"))!=subject:continue
        filt.append(r)
    if not filt:return None
    points=sorted({float(r["point"]) for r in filt if r.get("point") is not None})
    chosen_line=min(points,key=lambda z:abs(z-target_line)) if points else target_line
    same=[r for r in filt if r.get("point") is None or abs(float(r.get("point"))-chosen_line)<1e-9]
    if not same:return None
    prices=[r["price"] for r in same]
    median=float(np.median(prices)); best=max(same,key=lambda r:r["price"])
    return {
        "market_key":mk,"line":chosen_line,"side":side,"median":median,"best":float(best["price"]),
        "best_book":best["book"],"books":len(same),"min":min(prices),"max":max(prices),
        "last_update":max([str(r.get("last_update") or "") for r in same] or [""])
    }

def enrich_candidates_reference_odds(candidates,games_list):
    """Añade consenso de mercado y obliga a evaluar EXACTAMENTE la línea encontrada por la API."""
    if not odds_api_enabled():return candidates,{"enabled":False}
    events,usage0=odds_api_events(); out=[dict(x) for x in candidates]
    by_pk={g.get("game_pk"):g for g in games_list}; groups={}
    for i,x in enumerate(out):
        g=by_pk.get(x.get("game_pk")); ev=odds_event_for_game(g,events) if g else None; mk=_odds_market_key(x)
        if ev and mk:
            key=(x.get("game_pk"),ev.get("id"))
            groups.setdefault(key,{"markets":set(),"idx":[]})["markets"].add(mk)
            groups[key]["idx"].append(i)
    last_usage=usage0
    for (gpk,eid),meta in groups.items():
        data,u=odds_api_event_odds(eid,",".join(sorted(meta["markets"])))
        if u:last_usage=u
        for i in meta["idx"]:
            original=dict(out[i])
            q=reference_quote_from_event(original,data)
            if not q:continue

            original_line=float(original.get("line",q["line"]) or q["line"])
            market_line=float(q["line"])
            line_changed=abs(market_line-original_line)>.001
            priced=original

            # Regla V7.1.3: jamás usar la probabilidad de una línea para valorar otra.
            if line_changed:
                if original.get("sample_values") is None:
                    out[i].update({
                        "reference_quote":q,"reference_odds":q["median"],"reference_best_odds":q["best"],
                        "reference_line":market_line,"reference_books":q["books"],"reference_best_book":q["best_book"],
                        "original_model_line":original_line,"original_model_label":original.get("label"),
                        "line_repriced":False,"reference_verdict":"NO EVALUABLE","reference_ev_cons":None,
                    })
                    continue
                rp=v7_reprice_line(original,market_line,original.get("side","over"))
                if not rp:
                    out[i].update({
                        "reference_quote":q,"reference_odds":q["median"],"reference_best_odds":q["best"],
                        "reference_line":market_line,"reference_books":q["books"],"reference_best_book":q["best_book"],
                        "original_model_line":original_line,"original_model_label":original.get("label"),
                        "line_repriced":False,"reference_verdict":"NO EVALUABLE","reference_ev_cons":None,
                    })
                    continue
                priced=rp

            # Sustituimos la selección por la versión recalculada para que etiqueta, probabilidad,
            # conservadora, momio mínimo y EV correspondan TODOS a la misma línea.
            if line_changed:
                priced["original_model_line"]=original_line
                priced["original_model_label"]=original.get("label")
                priced["line_repriced"]=True
            else:
                priced["line_repriced"]=False

            priced["reference_quote"]=q
            priced["reference_odds"]=q["median"]
            priced["reference_best_odds"]=q["best"]
            priced["reference_line"]=market_line
            priced["reference_books"]=q["books"]
            priced["reference_best_book"]=q["best_book"]
            priced["reference_price_quality"]="FUERTE" if q["books"]>=3 else "MEDIA" if q["books"]==2 else "LIMITADA"
            pm=v7_price_metrics(priced,q["median"])
            priced["reference_model_prob"]=priced.get("prob")
            priced["reference_model_low"]=priced.get("prob_low")
            priced["reference_ev_cons"]=pm["ev_cons"]
            priced["reference_verdict"]=pm["verdict"]
            priced["reference_target_odds"]=pm["target"]
            priced["model_target_odds"]=pm["target"]
            out[i]=priced
    return out,{"enabled":True,**(last_usage or {})}


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
                "abstract_state":(g.get("status") or {}).get("abstractGameState",""),
                "detailed_state":(g.get("status") or {}).get("detailedState",""),
                "status_code":(g.get("status") or {}).get("statusCode",""),
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
    recent3=allowed[-3:]
    recent3_ra=sum(recent3)/len(recent3) if recent3 else recent_ra
    games_last3=len(recent3)
    fatigue_index=clamp_local((games_last3/3)*0.55 + max(0,recent3_ra-4.4)/6*0.45,0,1)
    return {
        "era":era,"whip":whip,"recent_ra_pg":recent_ra,
        "recent3_ra_pg":recent3_ra,"games_last3":games_last3,
        "fatigue_index":fatigue_index
    }

@st.cache_data(ttl=600)
def get_bullpen_workload(team_id,target_date):
    """Carga real reciente aproximada a partir de pitch counts de relevistas en boxscores MLB.
    No predice disponibilidad médica; mide uso observable en los 3 días previos.
    """
    target=datetime.strptime(target_date,"%Y-%m-%d").date()
    start=target-timedelta(days=3)
    total_pitches=0
    yesterday_pitches=0
    reliever_appearances=0
    heavy_arms=[]
    by_pitcher={}
    games_checked=0
    try:
        sched=_get(f"{BASE}/schedule",{
            "sportId":1,"teamId":team_id,"startDate":start.isoformat(),
            "endDate":(target-timedelta(days=1)).isoformat(),"gameType":"R"
        })
        game_rows=[]
        for d in sched.get("dates",[]):
            for g in d.get("games",[]):
                if g.get("status",{}).get("abstractGameState")!="Final": continue
                game_rows.append((d.get("date"),g.get("gamePk")))
        for dstr,gpk in game_rows[-3:]:
            if not gpk: continue
            try: box=_get(f"{BASE}/game/{gpk}/boxscore")
            except Exception: continue
            games_checked+=1
            side=None
            for s in ["away","home"]:
                tm=(box.get("teams") or {}).get(s,{})
                if (tm.get("team") or {}).get("id")==team_id:
                    side=s;break
            if side is None: continue
            tm=(box.get("teams") or {}).get(side,{})
            players=tm.get("players",{})
            for pid in tm.get("pitchers",[]) or []:
                pd=players.get(f"ID{pid}",{})
                pstat=((pd.get("stats") or {}).get("pitching") or {})
                if not pstat: continue
                gs=int(pstat.get("gamesStarted",0) or 0)
                if gs>0: continue
                pitches=int(pstat.get("pitchesThrown",0) or 0)
                if pitches<=0: continue
                name=(pd.get("person") or {}).get("fullName",str(pid))
                total_pitches+=pitches
                reliever_appearances+=1
                rec=by_pitcher.setdefault(name,{"pitches":0,"days":0,"yesterday":0})
                rec["pitches"]+=pitches;rec["days"]+=1
                if dstr==(target-timedelta(days=1)).isoformat():
                    yesterday_pitches+=pitches;rec["yesterday"]+=pitches
        for name,rec in by_pitcher.items():
            if rec["yesterday"]>=22 or rec["pitches"]>=38 or rec["days"]>=2:
                heavy_arms.append({"name":name,**rec})
    except Exception:
        return {"available":False,"games_checked":0,"total_pitches_3d":0,"yesterday_pitches":0,
                "reliever_appearances":0,"heavy_arms":[],"fatigue_score":.35}

    fatigue=0.0
    fatigue += min(total_pitches/180,.55)
    fatigue += min(yesterday_pitches/90,.25)
    fatigue += min(len(heavy_arms)*.07,.20)
    fatigue=clamp_local(fatigue,0,1)
    return {
        "available":games_checked>0,"games_checked":games_checked,
        "total_pitches_3d":total_pitches,"yesterday_pitches":yesterday_pitches,
        "reliever_appearances":reliever_appearances,"heavy_arms":heavy_arms,
        "fatigue_score":fatigue
    }

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
            pos=(pd.get("position") or {}).get("abbreviation") or (pd.get("position") or {}).get("code") or ""
            lineup.append({"id":pid,"name":person.get("fullName",f"Player {pid}"),"order":idx,"position":pos})
        result[side]=lineup
    return result


def _f(v,d=0.0):
    try:return float(v)
    except:return d

def clamp_local(x,lo,hi):
    return max(lo,min(hi,x))

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
                "ops":_f(s.get("ops"),.720),"avg":_f(s.get("avg"),.250),"obp":_f(s.get("obp"),.320),"slg":_f(s.get("slg"),.400),
                "pa":pa,"ab":int(s.get("atBats",0) or 0),
                "hits":int(s.get("hits",0) or 0),"doubles":int(s.get("doubles",0) or 0),"triples":int(s.get("triples",0) or 0),"hr":int(s.get("homeRuns",0) or 0),
                "runs":int(s.get("runs",0) or 0),"rbi":int(s.get("rbi",0) or 0),
                "tb":int(s.get("totalBases",0) or 0),"so":int(s.get("strikeOuts",0) or 0),"bb":int(s.get("baseOnBalls",0) or 0)
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
        return {"ops":.720,"avg":.250,"obp":.320,"slg":.400,"pa":0,"hits":0,"doubles":0,"triples":0,"hr":0,"runs":0,"rbi":0,"tb":0,"so":0,"bb":0,
                "hit_rate":.22,"single_rate":.145,"double_rate":.045,"triple_rate":.004,"hr_rate":.03,"tb_rate":.32,"hrr_rate":.42,"k_rate":.22,"bb_rate":.08,"iso":.150,
                "used_split":False,"stats_available":False}

    pa=max(overall["pa"],1)
    ops=split["ops"] if split and split["pa"]>=30 else overall["ops"]
    singles=max(0,overall["hits"]-overall["doubles"]-overall["triples"]-overall["hr"])
    return {**overall,"ops":ops,"iso":max(0.0,overall.get("slg",.400)-overall.get("avg",.250)),
            "hit_rate":overall["hits"]/pa,"single_rate":singles/pa,"double_rate":overall["doubles"]/pa,"triple_rate":overall["triples"]/pa,
            "hr_rate":overall["hr"]/pa,"tb_rate":overall["tb"]/pa,
            "hrr_rate":(overall["hits"]+overall["runs"]+overall["rbi"])/pa,"k_rate":overall["so"]/pa,"bb_rate":overall["bb"]/pa,
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
    recent3=shrink_mean(float(staff.get("recent3_ra_pg",recent)),3,LEAGUE_RPG,7)
    fatigue=float(staff.get("fatigue_index",0.35))
    workload=float(staff.get("workload_fatigue",fatigue))
    factor=(.35*(era/LEAGUE_ERA)+.18*(whip/LEAGUE_WHIP)+.22*(recent/LEAGUE_RPG)+
            .10*(recent3/LEAGUE_RPG)+.07*(1+fatigue*.22)+.08*(1+workload*.30))
    return clamp(factor,.82,1.30)

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

            opp_weighted=[]
            weights=[]
            lineup_weights=[1.10,1.08,1.06,1.04,1.02,1.00,.98,.96,.94]
            for idx,x in enumerate(opp_lineup[:9]):
                if x.get("stats_available") and x.get("k_rate") is not None:
                    w=lineup_weights[idx]
                    opp_weighted.append(float(x["k_rate"])*w)
                    weights.append(w)
            if opp_weighted and weights:
                raw_opp=sum(opp_weighted)/sum(weights)
                opp_k=shrink_mean(raw_opp,len(weights)*70,LEAGUE_K_PA,300)
            else:
                opp_k=LEAGUE_K_PA

            pitcher_k_rate=p.get("k_rate")
            if pitcher_k_rate:
                k_skill=shrink_mean(float(pitcher_k_rate),max(p.get("batters_faced",0),1),LEAGUE_K_PA,180)
                k_skill_factor=clamp(k_skill/LEAGUE_K_PA,.82,1.22)
            else:
                k_skill_factor=clamp(k9_reg/LEAGUE_K9,.82,1.22)

            matchup=clamp(opp_k/LEAGUE_K_PA,.88,1.13)
            base_mean=LEAGUE_K9*exp_ip/9
            mean_k=clamp(base_mean*k_skill_factor*matchup,1.5,9.8)

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

def _sample_prob(values,line,side):
    arr=np.asarray(values)
    if len(arr)==0:return .5
    if side=="over": return float(np.mean(arr>line))
    return float(np.mean(arr<line))

def _bands_from_sample_prob(p,confirmed,volatility):
    width=.045 if confirmed else .075
    if volatility=="medium": width+=.02
    elif volatility=="high": width+=.055
    return clamp(p-width,.01,.99),clamp(p+width,.01,.99)

def build_prop_candidates_v7(away_pitcher,home_pitcher,away_pitcher_name,home_pitcher_name,
                             away_lineup,home_lineup,lineups_confirmed=False):
    """V7: props con líneas Over/Under reales y distribución reutilizable para editar líneas."""
    props=[]
    for name,p,opp_lineup in [
        (away_pitcher_name,away_pitcher,home_lineup),
        (home_pitcher_name,home_pitcher,away_lineup),
    ]:
        if not p: continue
        ip=max(float(p.get("innings",0) or 0),0)
        k9_reg=shrink_mean(float(p.get("k9",LEAGUE_K9)),ip,LEAGUE_K9,50)
        exp_ip=shrink_mean(float(p.get("expected_ip",5.2)),max(p.get("games_started",0),1),5.15,12)
        exp_ip=clamp(exp_ip,4.4,6.3)
        opp_rates=[];weights=[]
        lw=[1.10,1.08,1.06,1.04,1.02,1.00,.98,.96,.94]
        for idx,x in enumerate(opp_lineup[:9]):
            if x.get("stats_available") and x.get("k_rate") is not None:
                opp_rates.append(float(x["k_rate"])*lw[idx]);weights.append(lw[idx])
        raw_opp=sum(opp_rates)/sum(weights) if weights else LEAGUE_K_PA
        opp_k=shrink_mean(raw_opp,len(weights)*70 if weights else 0,LEAGUE_K_PA,300)
        if p.get("k_rate"):
            k_skill=shrink_mean(float(p["k_rate"]),max(p.get("batters_faced",0),1),LEAGUE_K_PA,180)
            k_skill_factor=clamp(k_skill/LEAGUE_K_PA,.86,1.18)
        else:
            k_skill_factor=clamp(k9_reg/LEAGUE_K9,.86,1.18)
        matchup_factor=clamp(opp_k/LEAGUE_K_PA,.91,1.10)
        mean_k=clamp((LEAGUE_K9*exp_ip/9)*k_skill_factor*matchup_factor,1.5,9.2)
        rng=np.random.default_rng(stable_seed(name,"K-V7"))
        opp_lineup_confirmed = len(opp_lineup) >= 9 and lineups_confirmed
        cv=.20 if opp_lineup_confirmed else .26; shape=1/(cv**2)
        ks=rng.poisson(rng.gamma(shape,mean_k/shape,size=16000))
        for line in [2.5,3.5,4.5,5.5,6.5]:
            for side,word in [("over","Over"),("under","Under")]:
                prob=_sample_prob(ks,line,side); lo,hi=_bands_from_sample_prob(prob,opp_lineup_confirmed,"medium")
                props.append({
                    "category":"Pitcher Ks","label":f"{name} {word} {line:g} K",
                    "prob":prob,"prob_low":lo,"prob_high":hi,"agreement":.86 if opp_lineup_confirmed else .68,
                    "quality":86 if opp_lineup_confirmed else 68,"confirmed":opp_lineup_confirmed,"volatility":"medium",
                    "market_family":"pitcher_k","side":side,"line":line,"subject":name,"sample_values":ks,
                    "reason":f"V7.2.3 K audit · media ~{mean_k:.1f} K · K/9 regresado {k9_reg:.2f} · IP ~{exp_ip:.1f} · K% rival {opp_k*100:.1f}% · lineup rival {'confirmado' if opp_lineup_confirmed else 'provisional'}."
                })

    def hitters(lineup):
        for p in lineup[:9]:
            if not p.get("stats_available"): continue
            pa=expected_pa(p["order"]); sample=max(int(p.get("pa",0) or 0),0)
            confirmed=lineups_confirmed; q=88 if confirmed else 64
            split_adj=clamp(float(p.get("ops",LEAGUE_OPS))/LEAGUE_OPS,.88,1.12)
            rng=np.random.default_rng(stable_seed(p['name'],"HITTER-V7"))

            # V7.2.3: simulate PA outcomes (1B/2B/3B/HR/out) instead of a Poisson shortcut for total bases.
            npa=max(1,int(round(pa)))
            pr_single=shrink_mean(clamp(float(p.get("single_rate",.145))*split_adj,0,.35),sample,.145,140)
            pr_double=shrink_mean(clamp(float(p.get("double_rate",.045))*split_adj,0,.16),sample,.045,160)
            pr_triple=shrink_mean(clamp(float(p.get("triple_rate",.004))*split_adj,0,.04),sample,.004,220)
            pr_hr=shrink_mean(clamp(float(p.get("hr_rate",LEAGUE_HR_PA))*split_adj,0,.18),sample,LEAGUE_HR_PA,180)
            total_hit=pr_single+pr_double+pr_triple+pr_hr
            if total_hit>.62:
                scale=.62/total_hit; pr_single*=scale; pr_double*=scale; pr_triple*=scale; pr_hr*=scale
            probs=np.array([max(0,1-(pr_single+pr_double+pr_triple+pr_hr)),pr_single,pr_double,pr_triple,pr_hr],dtype=float)
            probs=probs/probs.sum()
            draws=rng.choice(5,size=(14000,npa),p=probs)
            hits=np.sum(draws>0,axis=1)
            tbs=np.sum(np.where(draws==1,1,np.where(draws==2,2,np.where(draws==3,3,np.where(draws==4,4,0)))),axis=1)
            hrs=np.sum(draws==4,axis=1)

            # HRR remains an event-count approximation, but it now uses OBP/SLG as a bounded quality-of-offense modifier.
            quality_adj=clamp((float(p.get("obp",.320))/.320)*.45 + (float(p.get("slg",.400))/.400)*.55,.82,1.18)
            hrr_rate=shrink_mean(clamp(float(p.get("hrr_rate",.42))*split_adj*quality_adj,0,1.5),sample,.42,170)
            hrr=rng.poisson(max(.05,hrr_rate*pa),size=14000)

            specs=[
                ("Hits", "hits", hits,[.5,1.5],"low"),
                ("Total Bases", "total_bases", tbs,[.5,1.5,2.5],"medium"),
                ("HRR", "hrr", hrr,[.5,1.5,2.5],"medium"),
                ("Home Run", "home_run", hrs,[.5],"high"),
            ]
            for cat,fam,vals,lines,vol in specs:
                for line in lines:
                    for side,word in [("over","Over"),("under","Under")]:
                        prob=_sample_prob(vals,line,side);lo,hi=_bands_from_sample_prob(prob,confirmed,vol)
                        props.append({
                            "category":cat,"label":f"{p['name']} {word} {line:g} {cat}",
                            "prob":prob,"prob_low":lo,"prob_high":hi,
                            "agreement":.90 if confirmed else .72,"quality":q if vol!="high" else max(55,q-12),
                            "confirmed":confirmed,"volatility":vol,"market_family":fam,"side":side,"line":line,
                            "subject":p['name'],"sample_values":vals,
                            "reason":f"V7.2.3 O/U · ~{pa:.1f} PA · turno #{p['order']} · perfil 1B/2B/3B/HR + OPS/OBP/SLG regresado."
                        })
    hitters(away_lineup);hitters(home_lineup)
    return props

def v7_price_metrics(item,odds):
    p=float(item.get("prob",.5)); pc=float(item.get("prob_low",p)); odds=max(float(odds),1.01)
    fair=1/max(p,.01); fair_cons=1/max(pc,.01); target=1.05/max(pc,.01)
    implied=1/odds; ev=p*odds-1; evc=pc*odds-1
    conf=item.get("confidence_score",confidence_score(item))
    vol=item.get("volatility","medium")
    # V7: decisión por precio, no sólo por probabilidad.
    if pc>=.55 and evc>=.06 and odds>=target and conf>=55:
        verdict="APOSTAR"
    elif pc>=.53 and evc>=.025 and odds>=fair_cons and conf>=48:
        verdict="CANDIDATO"
    else:
        verdict="PASS"
    return {"fair":fair,"fair_cons":fair_cons,"target":target,"implied":implied,"ev":ev,"ev_cons":evc,"verdict":verdict}

def v7_reprice_line(item,new_line,new_side):
    vals=item.get("sample_values")
    if vals is None: return None
    p=_sample_prob(vals,float(new_line),new_side)
    lo,hi=_bands_from_sample_prob(p,item.get("confirmed",False),item.get("volatility","medium"))
    x=dict(item);x["line"]=float(new_line);x["side"]=new_side
    word="Over" if new_side=="over" else "Under"
    x["label"]=f"{item.get('subject','Mercado')} {word} {float(new_line):g} {item.get('category','')}"
    x["prob"]=p;x["prob_low"]=lo;x["prob_high"]=hi;x["confidence_score"]=confidence_score(x)
    return x

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

def expert_risk_flags(item,both_lineups_confirmed,away_staff,home_staff,weather):
    flags=[]
    if not item.get("confirmed",False): flags.append("información todavía provisional")
    if item.get("agreement",1)<.80: flags.append("desacuerdo entre modelos")
    if item.get("prob_high",item["prob"])-item.get("prob_low",item["prob"])>.14: flags.append("rango de incertidumbre amplio")
    if item.get("volatility")=="high": flags.append("mercado de alta varianza")
    if "Full Game" in item.get("category",""):
        af=float((away_staff or {}).get("workload_fatigue",.35)); hf=float((home_staff or {}).get("workload_fatigue",.35))
        if max(af,hf)>.58: flags.append("bullpen con carga reciente relevante")
        flags.append("Full Game depende más del bullpen")
    if weather and weather.get("precip_probability",0)>=50: flags.append("riesgo meteorológico")
    return flags

def expert_support_factors(item,game,away_f5,home_f5,fg_total,park_factor,weather,both_lineups_confirmed):
    factors=[]
    label=item.get("label","")
    if item.get("agreement",0)>=.90: factors.append("consenso muy alto entre modelos")
    elif item.get("agreement",0)>=.82: factors.append("buen consenso entre modelos")
    if item.get("prob_low",0)>=.62: factors.append("probabilidad conservadora fuerte")
    if item.get("confidence_score",0)>=70: factors.append("confianza estadística alta")
    if both_lineups_confirmed: factors.append("lineups oficiales confirmados")
    if "Over" in label and park_factor>=1.04: factors.append("parque favorable a producción ofensiva")
    if "Under" in label and park_factor<=.97: factors.append("parque que reduce producción ofensiva")
    if weather:
        if weather.get("temp_f",72)>=85 and "Over" in label: factors.append("temperatura favorable al bateo")
        if weather.get("temp_f",72)<=58 and "Under" in label: factors.append("temperatura favorable al pitcheo")
    if "F5" in label: factors.append("reduce incertidumbre del bullpen")
    if "ponches" in label: factors.append("matchup K del pitcher contra el orden rival")
    if "hit" in label or "base" in label: factors.append("posición en lineup y tasa por PA regresada")
    return factors[:4]

def expert_read(item,game,away_f5,home_f5,fg_total,park_factor,weather,both_lineups_confirmed,away_staff,home_staff):
    supports=expert_support_factors(item,game,away_f5,home_f5,fg_total,park_factor,weather,both_lineups_confirmed)
    risks=expert_risk_flags(item,both_lineups_confirmed,away_staff,home_staff,weather)
    sc=item.get("confidence_score",0)
    if sc>=75 and item.get("prob_low",0)>=.60: stance="APOYA FUERTE"
    elif sc>=58 and item.get("prob_low",0)>=.56: stance="APOYA"
    elif sc>=48: stance="OBSERVAR"
    else: stance="EVITAR"
    return {"stance":stance,"supports":supports,"risks":risks,
            "main_risk":risks[0] if risks else "sin riesgo estructural dominante detectado"}

def build_avoid_list(items,selected_labels,max_items=4):
    avoids=[]
    for item in items:
        if item["label"] in selected_labels: continue
        x=dict(item);x["confidence_score"]=confidence_score(x)
        low=x.get("prob_low",x["prob"]); width=x.get("prob_high",x["prob"])-low
        reasons=[]
        if x["prob"]>=.60 and low<.54: reasons.append("porcentaje central atractivo pero piso conservador insuficiente")
        if x.get("agreement",1)<.76: reasons.append("desacuerdo alto")
        if width>.16: reasons.append("incertidumbre amplia")
        if x.get("volatility")=="high": reasons.append("varianza alta")
        if "Full Game BETA" in x.get("category","") and x["confidence_score"]<55: reasons.append("bullpen todavía domina la incertidumbre")
        if reasons:
            x["avoid_reasons"]=reasons
            x["avoid_score"]=len(reasons)*10 + max(0,.62-low)*100 + max(0,55-x["confidence_score"])/3
            avoids.append(x)
    return sorted(avoids,key=lambda x:x["avoid_score"],reverse=True)[:max_items]

def evaluate_selected_candidate_v6(item,odds):
    p=item["prob"]
    p_cons=item.get("prob_low",p)
    fair=prob_to_decimal(p)
    fair_conservative=prob_to_decimal(p_cons)
    ev=p*odds-1
    conservative_ev=p_cons*odds-1
    target=(1.05/max(p_cons,.01))
    confidence=item.get("confidence_score",0)

    # Coherencia:
    # si alcanza la cuota objetivo y EV conservador >=5%, puede ser APOSTAR
    # siempre que la confianza estadística mínima sea aceptable.
    if conservative_ev>=.05 and odds>=target and confidence>=50:
        verdict="APOSTAR"
    elif conservative_ev>=.015 and odds>=fair_conservative and confidence>=45:
        verdict="LEAN"
    else:
        verdict="PASS"

    score=conservative_ev*(max(confidence,1)/100)
    return {
        "ev":ev,
        "conservative_ev":conservative_ev,
        "fair_odds":fair,
        "fair_conservative":fair_conservative,
        "target_odds":target,
        "verdict":verdict,
        "score":score
    }



def format_game_time_cdmx(game_date_utc):
    """Convierte el gameDate ISO de MLB (UTC) a hora de Ciudad de México."""
    if not game_date_utc:
        return "Hora N/D"
    try:
        raw=str(game_date_utc).replace("Z","+00:00")
        dt=datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=ZoneInfo("UTC"))
        local=dt.astimezone(ZoneInfo("America/Mexico_City"))
        hour=local.strftime("%I").lstrip("0") or "12"
        minute=local.strftime("%M")
        ampm=local.strftime("%p")
        return f"{hour}:{minute} {ampm} CDMX"
    except Exception:
        return "Hora N/D"


# ================= V7 PRE-MARKET / PAPER TEST HELPERS =================
def parse_game_datetime_utc(game_date_utc):
    if not game_date_utc:
        return None
    try:
        raw=str(game_date_utc).replace("Z","+00:00")
        dt=datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("UTC"))
    except Exception:
        return None

def workload_label(score):
    score=float(score or 0)
    if score >= .66:
        return "🔴 ALTA"
    if score >= .36:
        return "🟡 MEDIA"
    return "🟢 BAJA"

def readiness_status(game, quality, both_confirmed, weather, away_pitch, home_pitch, away_bp_work, home_bp_work):
    reasons=[]
    dt=parse_game_datetime_utc(game.get("game_time_local"))
    now=datetime.now(ZoneInfo("UTC"))
    hours_to_game=(dt-now).total_seconds()/3600 if dt else None

    if not away_pitch or not home_pitch:
        return {
            "level":"RED","icon":"🔴","label":"NO CERRAR ANÁLISIS",
            "score":max(20,quality-25),
            "reasons":["falta al menos un abridor confirmado"],
            "hours_to_game":hours_to_game,
            "advice":"Espera a que MLB confirme ambos abridores."
        }

    if hours_to_game is not None and hours_to_game <= 0:
        reasons.append("el partido ya comenzó o está iniciando")
        return {
            "level":"RED","icon":"🔴","label":"PARTIDO INICIADO",
            "score":quality,"reasons":reasons,"hours_to_game":hours_to_game,
            "advice":"No congeles una nueva predicción pregame."
        }

    if not both_confirmed:
        reasons.append("faltan lineups oficiales")
    if weather is None:
        reasons.append("clima no disponible")
    if not away_bp_work.get("available") or not home_bp_work.get("available"):
        reasons.append("carga reciente de bullpen incompleta")

    if both_confirmed and weather is not None and away_bp_work.get("available") and home_bp_work.get("available") and quality >= 84:
        level,label,icon="GREEN","LISTO PARA PAPER TEST","🟢"
        advice="Los datos principales están completos. Puedes analizar y congelar la predicción."
    else:
        level,label,icon="YELLOW","ESPERAR / REVISAR","🟡"
        if hours_to_game is None:
            advice="Actualiza antes de cerrar la predicción."
        elif hours_to_game > 4:
            advice="Aún es temprano. Conviene volver a revisar 2–3 horas antes del juego."
        elif hours_to_game > 1:
            advice="Buena ventana para vigilar lineups y cambios de abridor."
        else:
            advice="Falta poco. Si continúan datos clave pendientes, no cierres una predicción de alta confianza."

    ready_score=quality
    if not both_confirmed: ready_score-=12
    if weather is None: ready_score-=5
    if not away_bp_work.get("available") or not home_bp_work.get("available"): ready_score-=5
    return {
        "level":level,"icon":icon,"label":label,"score":max(20,min(100,ready_score)),
        "reasons":reasons,"hours_to_game":hours_to_game,"advice":advice
    }

def make_context_snapshot(game, away_pitch, home_pitch, away_lineup, home_lineup, weather,
                          away_bp_work, home_bp_work, f5_total, fg_total):
    return {
        "away_pitcher":game.get("away_pitcher_name","TBD"),
        "home_pitcher":game.get("home_pitcher_name","TBD"),
        "away_lineup_count":len(away_lineup),
        "home_lineup_count":len(home_lineup),
        "temp_f":round(float(weather.get("temp_f",0)),1) if weather else None,
        "wind_mph":round(float(weather.get("wind_mph",0)),1) if weather else None,
        "away_bp":round(float(away_bp_work.get("fatigue_score",0)),2),
        "home_bp":round(float(home_bp_work.get("fatigue_score",0)),2),
        "f5_total":round(float(f5_total),2),
        "fg_total":round(float(fg_total),2),
    }

def context_changes(previous, current):
    if not previous:
        return []
    labels={
        "away_pitcher":"Abridor visitante",
        "home_pitcher":"Abridor local",
        "away_lineup_count":"Jugadores lineup visitante",
        "home_lineup_count":"Jugadores lineup local",
        "temp_f":"Temperatura °F",
        "wind_mph":"Viento mph",
        "away_bp":"Carga bullpen visitante",
        "home_bp":"Carga bullpen local",
        "f5_total":"Proyección total F5",
        "fg_total":"Proyección total Full Game",
    }
    out=[]
    for k,label in labels.items():
        a=previous.get(k); b=current.get(k)
        if a != b:
            if k in ("away_bp","home_bp") and a is not None and b is not None:
                out.append(f"{label}: {a*100:.0f}% → {b*100:.0f}%")
            else:
                out.append(f"{label}: {a} → {b}")
    return out

@st.cache_data(ttl=60)
def get_game_result_v65(game_pk):
    """Resultado final + F5 + stats individuales desde el feed oficial de juego de MLB para liquidar Paper Bets."""
    if not game_pk:
        return {"available":False,"final":False}
    try:
        data=requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
            headers=HEADERS,timeout=20
        ).json()
        status=((data.get("gameData") or {}).get("status") or {})
        abstract=status.get("abstractGameState","")
        detailed=status.get("detailedState","")
        final=abstract=="Final" or status.get("statusCode")=="F"

        live=data.get("liveData") or {}
        linescore=live.get("linescore") or {}
        teams=linescore.get("teams") or {}
        away_runs=int(((teams.get("away") or {}).get("runs") or 0))
        home_runs=int(((teams.get("home") or {}).get("runs") or 0))

        innings=linescore.get("innings") or []
        f5_away=f5_home=0
        complete_f5=len(innings)>=5
        if complete_f5:
            for inn in innings[:5]:
                f5_away += int((((inn.get("away") or {}).get("runs")) or 0))
                f5_home += int((((inn.get("home") or {}).get("runs")) or 0))

        player_stats={}
        box=(live.get("boxscore") or {}).get("teams") or {}
        for side in ("away","home"):
            players=(box.get(side) or {}).get("players") or {}
            for pd in players.values():
                name=((pd.get("person") or {}).get("fullName"))
                if not name:
                    continue
                batting=((pd.get("stats") or {}).get("batting") or {})
                pitching=((pd.get("stats") or {}).get("pitching") or {})
                player_stats[name]={
                    "hits":int(batting.get("hits",0) or 0),
                    "totalBases":int(batting.get("totalBases",0) or 0),
                    "homeRuns":int(batting.get("homeRuns",0) or 0),
                    "runs":int(batting.get("runs",0) or 0),
                    "rbi":int(batting.get("rbi",0) or 0),
                    "strikeOutsPitching":int(pitching.get("strikeOuts",0) or 0),
                }

        return {
            "available":True,"final":final,"abstract":abstract,"detailed":detailed,
            "away_runs":away_runs,"home_runs":home_runs,
            "f5_away":f5_away,"f5_home":f5_home,"complete_f5":complete_f5,
            "player_stats":player_stats
        }
    except Exception as e:
        return {"available":False,"final":False,"error":str(e)}

def compare_total(value, line, direction):
    if value > line:
        return "WON" if direction=="over" else "LOST"
    if value < line:
        return "LOST" if direction=="over" else "WON"
    return "PUSH"

def settle_market_v65(record, result):
    if not result.get("final"):
        return "PENDING", "Partido aún no finaliza"

    market=record.get("market","")
    away=record.get("away_abbr","")
    home=record.get("home_abbr","")

    m=re.fullmatch(r"F5 (Over|Under) ([0-9.]+)",market,re.I)
    if m:
        if not result.get("complete_f5"):
            return "UNSUPPORTED","No hay 5 entradas completas"
        direction=m.group(1).lower(); line=float(m.group(2))
        total=result["f5_away"]+result["f5_home"]
        return compare_total(total,line,direction),f"F5 terminó {result['f5_away']}-{result['f5_home']} (total {total})"

    m=re.fullmatch(r"Full Game (Over|Under) ([0-9.]+)",market,re.I)
    if m:
        direction=m.group(1).lower(); line=float(m.group(2))
        total=result["away_runs"]+result["home_runs"]
        return compare_total(total,line,direction),f"Final {result['away_runs']}-{result['home_runs']} (total {total})"

    m=re.fullmatch(r"([A-Z]{2,4}) F5 ML",market)
    if m:
        if not result.get("complete_f5"):
            return "UNSUPPORTED","No hay 5 entradas completas"
        team=m.group(1)
        if result["f5_away"]==result["f5_home"]:
            return "PUSH",f"F5 empatado {result['f5_away']}-{result['f5_home']}"
        winner=away if result["f5_away"]>result["f5_home"] else home
        return ("WON" if team==winner else "LOST"),f"F5 {away} {result['f5_away']} - {home} {result['f5_home']}"

    m=re.fullmatch(r"([A-Z]{2,4}) ML Full Game",market)
    if m:
        team=m.group(1)
        if result["away_runs"]==result["home_runs"]:
            return "PUSH","Juego empatado"
        winner=away if result["away_runs"]>result["home_runs"] else home
        return ("WON" if team==winner else "LOST"),f"Final {away} {result['away_runs']} - {home} {result['home_runs']}"

    m=re.fullmatch(r"(.+?) ([0-9]+)\+ ponches",market,re.I)
    if m:
        name=m.group(1); need=int(m.group(2))
        stat=(result.get("player_stats") or {}).get(name)
        if stat is None:
            return "UNSUPPORTED",f"No encontré stats de {name}"
        got=stat["strikeOutsPitching"]
        return ("WON" if got>=need else "LOST"),f"{name}: {got} K"

    m=re.fullmatch(r"(.+?) ([0-9]+)\+ hits?",market,re.I)
    if m:
        name=m.group(1); need=int(m.group(2))
        stat=(result.get("player_stats") or {}).get(name)
        if stat is None:
            return "UNSUPPORTED",f"No encontré stats de {name}"
        got=stat["hits"]
        return ("WON" if got>=need else "LOST"),f"{name}: {got} hits"

    m=re.fullmatch(r"(.+?) ([0-9]+)\+ bases? totales?",market,re.I)
    if not m:
        m=re.fullmatch(r"(.+?) ([0-9]+)\+ base total",market,re.I)
    if m:
        name=m.group(1); need=int(m.group(2))
        stat=(result.get("player_stats") or {}).get(name)
        if stat is None:
            return "UNSUPPORTED",f"No encontré stats de {name}"
        got=stat["totalBases"]
        return ("WON" if got>=need else "LOST"),f"{name}: {got} TB"

    m=re.fullmatch(r"(.+?) ([0-9]+)\+ HR",market,re.I)
    if m:
        name=m.group(1); need=int(m.group(2))
        stat=(result.get("player_stats") or {}).get(name)
        if stat is None:
            return "UNSUPPORTED",f"No encontré stats de {name}"
        got=stat["homeRuns"]
        return ("WON" if got>=need else "LOST"),f"{name}: {got} HR"

    return "UNSUPPORTED","Mercado todavía no tiene resolución automática"

def normalize_paper_row(row):
    numeric_float=["prob_central","prob_low","prob_high","agreement","odds","stake","stake_mxn","unit_value_mxn","hours_to_game_at_freeze"]
    numeric_int=["confidence","game_pk","away_lineup_count","home_lineup_count"]
    for k in numeric_float:
        try: row[k]=float(row.get(k,0) or 0)
        except Exception: row[k]=0.0
    for k in numeric_int:
        try: row[k]=int(float(row.get(k,0) or 0))
        except Exception: row[k]=0
    for k in ["confirmed","away_lineup_confirmed","home_lineup_confirmed","both_lineups_confirmed"]:
        if isinstance(row.get(k),str):
            row[k]=row[k].lower() in ("true","1","yes","sí","si")
    if str(row.get("readiness_level","")).upper()=="GREEN":
        row["freeze_type"]="FINAL"
    return row

def paper_metrics(records):
    settled=[r for r in records if r.get("result") in ("WON","LOST","PUSH")]
    decided=[r for r in settled if r.get("result") in ("WON","LOST")]
    wins=sum(r["result"]=="WON" for r in decided)
    losses=sum(r["result"]=="LOST" for r in decided)
    pushes=sum(r["result"]=="PUSH" for r in settled)

    profit=0.0; stake_total=0.0
    briers=[]; logloss=[]
    eps=1e-6
    for r in settled:
        stake=float(r.get("stake_mxn",0) or 0)
        if stake <= 0:
            stake=float(r.get("stake",1) or 1)*float(r.get("unit_value_mxn",50) or 50)
        odds=float(r.get("odds",0) or 0)
        stake_total+=stake
        if r["result"]=="WON": profit += stake*(odds-1)
        elif r["result"]=="LOST": profit -= stake

    for r in decided:
        # Registros reconstruidos desde screenshots no tienen la probabilidad original y NO calibran.
        if "RECOVERED" in str(r.get("model_version","")).upper():
            continue
        try: rawp=float(r.get("prob_central"))
        except Exception: continue
        if rawp<=0 or rawp>=1: continue
        y=1.0 if r["result"]=="WON" else 0.0
        p=clamp(rawp,eps,1-eps)
        briers.append((p-y)**2)
        logloss.append(-(y*math.log(p)+(1-y)*math.log(1-p)))

    return {
        "settled":len(settled),"decided":len(decided),"wins":wins,"losses":losses,"pushes":pushes,
        "hit_rate":wins/len(decided) if decided else None,
        "profit":profit,"roi":profit/stake_total if stake_total else None,
        "brier":sum(briers)/len(briers) if briers else None,
        "logloss":sum(logloss)/len(logloss) if logloss else None,
    }

def calibration_rows(records):
    decided=[r for r in records if r.get("result") in ("WON","LOST") and "RECOVERED" not in str(r.get("model_version","")).upper()]
    buckets=[(.50,.60,"50–59%"),(.60,.70,"60–69%"),(.70,.80,"70–79%"),(.80,1.01,"80%+")]
    rows=[]
    for lo,hi,label in buckets:
        group=[r for r in decided if lo<=float(r.get("prob_central",0))<hi]
        if not group:
            continue
        avgp=sum(float(r["prob_central"]) for r in group)/len(group)
        actual=sum(r["result"]=="WON" for r in group)/len(group)
        rows.append({"Rango":label,"N":len(group),"Prob. media":f"{avgp*100:.1f}%","Acierto real":f"{actual*100:.1f}%"})
    return rows


def readiness_aware_verdict(base_verdict, readiness_level):
    """
    The statistical model can like a market before all pregame data is complete.
    UI presentation is stricter:
    GREEN  -> show intrinsic verdict.
    YELLOW -> never show APOSTAR; downgrade to CANDIDATO/LEAN.
    RED    -> NO CERRAR.
    """
    if readiness_level == "RED":
        return "NO CERRAR"
    if readiness_level == "YELLOW":
        if base_verdict == "APOSTAR":
            return "CANDIDATO"
        return base_verdict
    return base_verdict

def readiness_verdict_icon(verdict):
    return {
        "APOSTAR":"🟢",
        "CANDIDATO":"🟡",
        "LEAN":"🟡",
        "PASS":"⚪",
        "NO CERRAR":"🔴",
    }.get(verdict,"⚪")


# ================= V7.2 DECISION / EXPRESS HELPERS =================
def game_start_cdmx(g):
    try:
        raw=g.get("game_time_local")
        if not raw: return None
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        return dt.astimezone(CDMX_TZ)
    except Exception:
        return None

def game_is_pregame(g,now=None):
    now=now or now_cdmx()
    state=str(g.get("abstract_state") or "").lower()
    code=str(g.get("status_code") or "").upper()
    if state in ("live","final") or code in ("I","F","O"):
        return False
    if state in ("preview","pregame"):
        return True
    # Fallback only when MLB did not provide a useful state.
    start=game_start_cdmx(g)
    return bool(start is None or start>now)

def risk_profile_v72(item):
    low=float(item.get("prob_low",item.get("prob",.5)))
    conf=float(item.get("confidence_score",confidence_score(item)))
    width=float(item.get("prob_high",item.get("prob",.5)))-low
    vol=item.get("volatility","medium")
    confirmed=bool(item.get("confirmed",False))
    penalty=0
    if vol=="high": penalty+=2
    elif vol=="medium": penalty+=1
    if not confirmed: penalty+=1
    if width>.15: penalty+=1
    if low>=.66 and conf>=72 and penalty<=1: return "BAJO","🟢"
    if low>=.58 and conf>=58 and penalty<=2: return "MEDIO","🟡"
    return "ALTO","🟠"

def express_safety_score_v721(item,use_odds=False):
    """Rank for the user's main goal: highest hit probability with controlled uncertainty.
    Odds are optional and only a secondary signal; they never create a pick by themselves.
    """
    low=float(item.get("prob_low",item.get("prob",.5)))
    conf=float(item.get("confidence_score",confidence_score(item)))/100
    width=max(0,float(item.get("prob_high",item.get("prob",.5)))-low)
    vol=item.get("volatility","medium")
    risk_pen={"low":0.0,"medium":.035,"high":.12}.get(vol,.04)
    # Conservative probability dominates. Confidence and narrow uncertainty are next.
    score=low*.68+conf*.27-width*.18-risk_pen
    if use_odds and item.get("reference_odds"):
        # Price is useful, but deliberately capped so a giant EV cannot outrank a much safer pick.
        evc=float(item.get("reference_ev_cons",0) or 0)
        score += max(-.04,min(.06,evc*.08))
    return score

def express_qualifies_v721(item,use_odds=False):
    low=float(item.get("prob_low",item.get("prob",.5)))
    conf=float(item.get("confidence_score",confidence_score(item)))
    # Safety-first admission. High-volatility markets need stronger numbers.
    vol=item.get("volatility","medium")
    if vol=="high":
        base=(low>=.68 and conf>=72)
    else:
        base=(low>=.61 and conf>=62)
    if not base:
        return False
    if use_odds:
        # If the user asks to use market prices, require a real reference quote and avoid a clear PASS.
        return bool(item.get("reference_odds")) and item.get("reference_verdict")!="PASS"
    return True

def market_group_v722(item):
    fam=str(item.get("market_family","") or "")
    if fam.startswith("f5_"): return "F5 / juego"
    if fam.startswith("fg_"): return "Full Game"
    if fam=="pitcher_k": return "Pitcher props"
    if fam in {"hits","total_bases","hrr","home_run"}: return "Batter props"
    cat=str(item.get("category","") or "")
    if "F5" in cat: return "F5 / juego"
    if "Full Game" in cat: return "Full Game"
    if "Pitcher" in cat: return "Pitcher props"
    return "Batter props"

def family_shortlist_v722(items, per_group=8):
    """V7.2.4: preserva candidatos de TODAS las familias sin borrarlos por umbrales tempranos.
    La clasificación APOSTAR/PASS se hace después. Así Express nunca aparenta no haber analizado.
    """
    enriched=[]
    for item in items:
        x=dict(item)
        x["confidence_score"]=confidence_score(x)
        x["express_group"]=market_group_v722(x)
        enriched.append(x)
    out=[]
    for group in ["F5 / juego","Full Game","Pitcher props","Batter props"]:
        g=[x for x in enriched if x["express_group"]==group]
        g=sorted(g,key=lambda x:(x.get("prob_low",0),x.get("confidence_score",0),x.get("prob",0)),reverse=True)
        # Mantiene un bloque amplio de cada familia para el ranking global y el fallback.
        out.extend(g[:max(per_group,12)])
    return out

def diversify_express_v721(pool,target_n,max_per_game=1,automatic=True,allowed_groups=None):
    """V7.2.3: una sola familia no puede monopolizar Express."""
    allowed_groups=set(allowed_groups or ["F5 / juego","Full Game","Pitcher props","Batter props"])
    pool=[x for x in pool if market_group_v722(x) in allowed_groups]
    if not automatic: return pool[:target_n]
    selected=[]; game_counts={}; player_counts={}; group_counts={}
    caps={
        "Pitcher props": min(2,max(1,math.ceil(target_n*.20))),
        "Batter props": max(1,math.ceil(target_n*.30)),
        "F5 / juego": max(1,math.ceil(target_n*.40)),
        "Full Game": min(2,max(1,math.ceil(target_n*.20))),
    }
    grouped={}
    for x in pool: grouped.setdefault(market_group_v722(x),[]).append(x)
    for g in grouped: grouped[g]=sorted(grouped[g],key=lambda z:z.get("express_safety_score",-9),reverse=True)
    order=[g for g in ["F5 / juego","Batter props","Full Game","Pitcher props"] if g in allowed_groups]
    idx={g:0 for g in order}; progress=True
    while len(selected)<target_n and progress:
        progress=False
        for group in order:
            if len(selected)>=target_n: break
            if group_counts.get(group,0)>=caps.get(group,target_n): continue
            arr=grouped.get(group,[])
            while idx[group] < len(arr):
                x=arr[idx[group]]; idx[group]+=1
                game=x.get("game"); subj=x.get("subject","")
                if game_counts.get(game,0)>=max_per_game: continue
                if group in {"Pitcher props","Batter props"} and subj and player_counts.get(subj,0)>=1: continue
                selected.append(x); progress=True
                game_counts[game]=game_counts.get(game,0)+1; group_counts[group]=group_counts.get(group,0)+1
                if group in {"Pitcher props","Batter props"} and subj: player_counts[subj]=1
                break
    return selected

# ================= V7 EXPRESS ENGINE =================
def analyze_game_express_v7(g,selected_date):
    d=selected_date.isoformat() if hasattr(selected_date,"isoformat") else str(selected_date)
    season=selected_date.year if hasattr(selected_date,"year") else int(d[:4])
    away_form=get_team_form(g["away_id"],d);home_form=get_team_form(g["home_id"],d)
    away_pitch=get_pitcher_stats(g["away_pitcher_id"],season) if g.get("away_pitcher_id") else None
    home_pitch=get_pitcher_stats(g["home_pitcher_id"],season) if g.get("home_pitcher_id") else None
    raw=get_lineups(g["game_pk"])
    away_lineup=enrich_lineup(raw.get("away",[]),season,(home_pitch or {}).get("hand","R"))
    home_lineup=enrich_lineup(raw.get("home",[]),season,(away_pitch or {}).get("hand","R"))
    both=len(away_lineup)>=9 and len(home_lineup)>=9
    park=get_stadium_context(g["home_abbr"]);weather=get_weather(park["lat"],park["lon"],d,g.get("game_time_local")) if park else None
    q=100
    if not g.get("away_pitcher_id") or not g.get("home_pitcher_id"):q-=18
    if len(away_lineup)<9:q-=12
    if len(home_lineup)<9:q-=12
    if weather is None:q-=8
    q=max(30,min(100,q))
    pf=(park or {}).get("factor",1.0)
    af,ad=project_f5_ensemble(away_form,home_pitch,away_lineup,len(away_lineup)>=9,pf,weather)
    hf,hd=project_f5_ensemble(home_form,away_pitch,home_lineup,len(home_lineup)>=9,pf,weather)
    sim=simulate_run_environment(af,hf,q,both,stable_seed(g["game_pk"],d,"EXPRESS"),n=7000,full_game=False,model_disagreement=ad["model_disagreement"]+hd["model_disagreement"])
    items=[]
    totalvals=sim["away"]+sim["home"]
    for line in [3.5,4.5,5.5,6.5]:
        for side,word in [("over","Over"),("under","Under")]:
            p0=_sample_prob(totalvals,line,side);lo,hi=_bands_from_sample_prob(p0,both,"medium")
            items.append({"category":"F5","label":f"F5 {word} {line:g}","prob":p0,"prob_low":lo,"prob_high":hi,
                          "agreement":.90 if both else .75,"quality":q,"confirmed":both,"volatility":"medium",
                          "market_family":"f5_total","side":side,"line":line,"sample_values":totalvals,"subject":f"{g['away_abbr']} @ {g['home_abbr']}"})
    # F5 moneyline candidates help diversify away from player props.
    for side,abbr in [("away",g["away_abbr"]),("home",g["home_abbr"])]:
        p0=sim_ml_prob(sim,side); lo,hi=_bands_from_sample_prob(p0,both,"medium")
        items.append({"category":"F5","label":f"{abbr} F5 ML","prob":p0,"prob_low":lo,"prob_high":hi,
                      "agreement":.86 if both else .72,"quality":q,"confirmed":both,"volatility":"medium",
                      "market_family":"f5_ml","side":side,"line":0.0,"sample_values":None,"subject":abbr})

    # Lightweight Full Game totals. Bullpen/staff adds uncertainty; these must clear the same conservative filters.
    away_staff=get_team_pitching_profile(g["away_id"],season,d)
    home_staff=get_team_pitching_profile(g["home_id"],season,d)
    away_fg,home_fg,_=project_full_game_ensemble(af,hf,away_form,home_form,away_staff,home_staff,pf,weather)
    fgsim=simulate_run_environment(away_fg,home_fg,max(35,q-8),False,stable_seed(g["game_pk"],d,"EXPRESS-FG"),n=6000,full_game=True,model_disagreement=ad["model_disagreement"]+hd["model_disagreement"])
    fgvals=fgsim["away"]+fgsim["home"]
    for line in [7.5,8.5,9.5,10.5]:
        for side,word in [("over","Over"),("under","Under")]:
            p0=_sample_prob(fgvals,line,side); lo,hi=_bands_from_sample_prob(p0,False,"medium")
            items.append({"category":"Full Game","label":f"Full Game {word} {line:g}","prob":p0,"prob_low":lo,"prob_high":hi,
                          "agreement":.78,"quality":max(35,q-8),"confirmed":False,"volatility":"medium",
                          "market_family":"fg_total","side":side,"line":line,"sample_values":fgvals,"subject":f"{g['away_abbr']} @ {g['home_abbr']}"})

    # Full Game Moneyline: ganador del partido completo.
    for side,abbr in [("away",g["away_abbr"]),("home",g["home_abbr"])]:
        p0=sim_ml_prob(fgsim,side); lo,hi=_bands_from_sample_prob(p0,False,"medium")
        items.append({"category":"Full Game","label":f"{abbr} ML Full Game","prob":p0,"prob_low":lo,"prob_high":hi,
                      "agreement":.76,"quality":max(35,q-8),"confirmed":False,"volatility":"medium",
                      "market_family":"fg_ml","side":side,"line":0.0,"sample_values":None,"subject":abbr})

    items.extend(build_prop_candidates_v7(away_pitch,home_pitch,g['away_pitcher_name'],g['home_pitcher_name'],away_lineup,home_lineup,both))
    ranked=family_shortlist_v722(items,per_group=8)
    for x in ranked:
        x["game"]=g["label"];x["game_pk"]=g["game_pk"];x["game_time_cdmx"]=format_game_time_cdmx(g.get("game_time_local"));x["data_quality"]=q;x["both_lineups_confirmed"]=both
        # Precio mínimo como referencia de modelo; no se presenta como cuota de sportsbook.
        x["model_target_odds"]=1.05/max(x.get("prob_low",x["prob"]),.01)
    return ranked,{"quality":q,"both":both}

# ================= APP UI =================
st.set_page_config(page_title="MLB Betting Hub V7.2.4", page_icon="⚾", layout="wide")
st.title("⚾ MLB Betting Hub — V7.2.4 Alpha")
st.caption("V7.2.4: Express siempre devuelve un Top útil + ranking por familias + momios opcionales + edición dentro del Top.")
st.info("🧪 **V7.2.4 ALPHA** — Si no hay picks verdes, Express muestra las mejores alternativas por probabilidad con su riesgo claramente marcado. Full Game incluye ganador (Moneyline) y totales.")

c1,c2=st.columns([1,2])
with c1:
    selected_date=st.date_input("📅 Fecha",value=date.today())

games=get_schedule(selected_date.isoformat())
if not games:
    st.warning("No encontré partidos MLB para esta fecha o MLB no respondió.")
    st.stop()

with c2:
    game_options = {
        f"{g['label']} — {format_game_time_cdmx(g.get('game_time_local'))}": g
        for g in games
    }
    game_label = st.selectbox("⚾ Partido", list(game_options.keys()))
game = game_options[game_label]

game_state_key=f"{selected_date.isoformat()}-{game['game_pk']}"
if st.session_state.get("v653_game_key")!=game_state_key:
    st.session_state["v653_game_key"]=game_state_key
    st.session_state["v653_analysis_ready"]=False

with st.spinner("Consultando MLB, contexto y lineups..."):
    away_form=get_team_form(game["away_id"],selected_date.isoformat())
    home_form=get_team_form(game["home_id"],selected_date.isoformat())
    away_pitch=get_pitcher_stats(game["away_pitcher_id"],selected_date.year) if game["away_pitcher_id"] else None
    home_pitch=get_pitcher_stats(game["home_pitcher_id"],selected_date.year) if game["home_pitcher_id"] else None
    away_staff=get_team_pitching_profile(game["away_id"],selected_date.year,selected_date.isoformat())
    home_staff=get_team_pitching_profile(game["home_id"],selected_date.year,selected_date.isoformat())
    away_bp_work=get_bullpen_workload(game["away_id"],selected_date.isoformat())
    home_bp_work=get_bullpen_workload(game["home_id"],selected_date.isoformat())
    if away_staff is not None: away_staff={**away_staff,"workload_fatigue":away_bp_work.get("fatigue_score",.35)}
    if home_staff is not None: home_staff={**home_staff,"workload_fatigue":home_bp_work.get("fatigue_score",.35)}

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

props=build_prop_candidates_v7(
    away_pitch,home_pitch,game["away_pitcher_name"],game["home_pitcher_name"],
    away_lineup,home_lineup,both_confirmed
)

# =========================
# Contexto visible
# =========================
st.caption("ℹ️ Express usa el contexto automáticamente. Está oculto para mantener la pantalla simple.")
with st.expander("🔍 Ver contexto del partido seleccionado", expanded=False):
    st.divider()
    st.subheader("📋 Contexto del partido")
    st.caption(f"🕒 Hora de inicio CDMX: **{format_game_time_cdmx(game.get('game_time_local'))}**")

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

    st.markdown("### 🧯 Bullpen y catcher")
    bp1,bp2=st.columns(2)
    with bp1:
        catcher=next((p for p in away_lineup if p.get("position")=="C"),None)
        st.write(f"**{game['away_abbr']}** · Catcher: {catcher['name'] if catcher else 'N/D'}")
        if away_bp_work.get("available"):
            st.caption(
                f"Relevistas: {away_bp_work['total_pitches_3d']} pitcheos últimos 3 días · "
                f"{away_bp_work['yesterday_pitches']} ayer · carga {workload_label(away_bp_work['fatigue_score'])} ({away_bp_work['fatigue_score']*100:.0f}%)"
            )
            if away_bp_work.get("heavy_arms"):
                st.caption("Brazos cargados: "+", ".join(x["name"] for x in away_bp_work["heavy_arms"][:3]))
        else: st.caption("Carga de bullpen: N/D")
    with bp2:
        catcher=next((p for p in home_lineup if p.get("position")=="C"),None)
        st.write(f"**{game['home_abbr']}** · Catcher: {catcher['name'] if catcher else 'N/D'}")
        if home_bp_work.get("available"):
            st.caption(
                f"Relevistas: {home_bp_work['total_pitches_3d']} pitcheos últimos 3 días · "
                f"{home_bp_work['yesterday_pitches']} ayer · carga {workload_label(home_bp_work['fatigue_score'])} ({home_bp_work['fatigue_score']*100:.0f}%)"
            )
            if home_bp_work.get("heavy_arms"):
                st.caption("Brazos cargados: "+", ".join(x["name"] for x in home_bp_work["heavy_arms"][:3]))
        else: st.caption("Carga de bullpen: N/D")

    st.caption(
        f"Última consulta: {now_cdmx().strftime('%H:%M:%S')} · Calidad de datos {quality}/100 · "
        "refresco automático aproximado cada 2 minutos."
    )

    # Semáforo pregame V7
    ready=readiness_status(
        game,quality,both_confirmed,weather,away_pitch,home_pitch,away_bp_work,home_bp_work
    )
    st.markdown("### 🚦 Estado para cerrar una predicción")
    r1,r2,r3=st.columns([1,1,1.6])
    r1.metric("Semáforo",f"{ready['icon']} {ready['label']}")
    r2.metric("Preparación",f"{ready['score']}/100")
    if ready.get("hours_to_game") is not None:
        r3.metric("Tiempo al juego",f"{max(0,ready['hours_to_game']):.1f} h")
    else:
        r3.metric("Tiempo al juego","N/D")
    st.caption(ready["advice"])
    if ready["reasons"]:
        st.caption("Pendiente: " + " · ".join(ready["reasons"]))
    st.caption("V7.2.3 mejora la simulación de bateadores con perfil 1B/2B/3B/HR, OBP/SLG y splits disponibles. Statcast/Savant completo sigue pendiente de integración validada.")

    current_context_snapshot=make_context_snapshot(
        game,away_pitch,home_pitch,away_lineup,home_lineup,weather,
        away_bp_work,home_bp_work,f5_total,fg_total
    )
    changes=context_changes(st.session_state.get("v653_previous_context"),current_context_snapshot)
    if changes:
        with st.expander("🆕 Qué cambió desde tu última actualización",expanded=True):
            for ch in changes:
                st.write(f"• {ch}")

    b1,b2,sp=st.columns([1,1,2.2])
    with b1:
        update_now=st.button("🔄 Actualizar datos",use_container_width=True,type="secondary")
    with b2:
        analyze_now=st.button("🧠 Analizar partido",use_container_width=True,type="primary")

    if update_now:
        st.session_state["v653_previous_context"]=current_context_snapshot
        st.cache_data.clear()
        st.session_state["v653_analysis_ready"]=False
        st.rerun()
    if analyze_now:
        st.session_state["v653_analysis_ready"]=True


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
            "market_family":"f5_total","side":direction,"line":line,"subject":f"{game['away_abbr']} @ {game['home_abbr']}",
            "sample_values":f5_sim["away"]+f5_sim["home"],
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
            "market_family":"fg_total","side":direction,"line":line,"subject":f"{game['away_abbr']} @ {game['home_abbr']}",
            "sample_values":fg_sim["away"]+fg_sim["home"],
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

# Resumen de todo lo analizado y mercados cercanos a calificar
def build_analysis_summary(items, selected):
    selected_labels={x["label"] for x in selected}
    enriched=[]
    for item in items:
        x=dict(item)
        x["confidence_score"]=confidence_score(x)
        x["passes_lower_bound"]=x.get("prob_low",x["prob"])>=.54
        x["passes_confidence"]=x["confidence_score"]>=48
        x["passes"]=x["passes_lower_bound"] and x["passes_confidence"]
        # Cercanía al umbral, priorizando mercados que fallaron por poco
        lb_gap=max(0,.54-x.get("prob_low",x["prob"]))
        conf_gap=max(0,48-x["confidence_score"])
        x["near_score"]=lb_gap*100 + conf_gap/8
        enriched.append(x)

    passed=[x for x in enriched if x["passes"]]
    near=[x for x in enriched if not x["passes"] and x["label"] not in selected_labels]
    near=sorted(near,key=lambda x:(x["near_score"],-x["confidence_score"],-x["prob"]))[:5]
    return {
        "total":len(enriched),
        "passed":len(passed),
        "discarded":len(enriched)-len(passed),
        "near":near
    }

analysis_summary=build_analysis_summary(automatic,ranked_auto)
avoid_list=build_avoid_list(automatic,{x["label"] for x in ranked_auto},max_items=4)

# Registros de prueba en sesión
if "v653_history" not in st.session_state:
    st.session_state["v653_history"]=[]
if "v653_paper_bets" not in st.session_state:
    st.session_state["v653_paper_bets"]=persistent_load_paper_bets()
if persistent_store_enabled():
    st.caption("💾 Paper Bets: Supabase activo + respaldo local.")
else:
    st.caption("💾 Paper Bets: respaldo local activo para F5/reruns. Para sobrevivir redeploy/reinicio del servidor, configura Supabase una sola vez.")

# =========================
# Pantallas
# =========================
tabExpress,tab1,tab2,tabParlay,tab4,tab5=st.tabs([
    "⚡ Express","🔍 Partido","💵 Evaluar momios","🎟️ Parlays","🧪 Paper Bets","📊 Rendimiento"
])

with tab1:
    st.subheader(f"🧠 Análisis estadístico {game['away_abbr']} @ {game['home_abbr']}")
    q1,q2,q3=st.columns([1,1,1.4])
    q1.metric("Calidad de datos",f"{quality}/100")
    q2.metric("Lineups","✅ Confirmados" if both_confirmed else "⚠️ Provisional")
    q3.caption("V7.2.3 separa probabilidad, confianza y riesgo; no ordena solo por porcentaje central.")

    if not both_confirmed:
        st.warning("Faltan lineups. V7.2.3 amplía automáticamente la incertidumbre y reduce la confianza de props/bateadores.")

    s1,s2,s3=st.columns(3)
    s1.metric("Mercados analizados",analysis_summary["total"])
    s2.metric("Pasaron filtros",analysis_summary["passed"])
    s3.metric("Descartados",analysis_summary["discarded"])

    if not st.session_state.get("v653_analysis_ready",False):
        st.info("👆 Revisa el contexto y pulsa **🧠 Analizar partido**.")
    elif not ranked_auto:
        st.info("⚪ PASS ESTADÍSTICO — No encontré suficientes opciones robustas. V5 no fuerza cinco picks.")
    else:
        st.markdown("### 🏆 Oportunidades más robustas")
        for i,item in enumerate(ranked_auto,1):
            sc=item["confidence_score"]
            icon="🟢" if sc>=72 else "🟡" if sc>=58 else "⚪"
            if "ponches" in item["label"].lower():
                pitcher_state="⚾ Pitcher confirmado ✅" if item.get("confirmed") else "⚾ Pitcher pendiente ⚠️"
                lineup_state=f"👥 Lineup rival {'confirmado ✅' if both_confirmed else 'pendiente ⚠️'}"
                predictor_state="📊 PREDICCIÓN FINAL" if both_confirmed else "📊 PREDICCIÓN PROVISIONAL"
                detail_state=f"{pitcher_state} · {lineup_state}"
            else:
                predictor_state="📊 PREDICCIÓN FINAL" if both_confirmed else "📊 PREDICCIÓN PROVISIONAL"
                detail_state=f"👥 Lineups {'confirmados ✅' if both_confirmed else 'pendientes ⚠️'}"
            st.markdown(
                f"**{i}. {icon} {item['label']}**  \n"
                f"Prob. central **{item['prob']*100:.1f}%** · "
                f"Rango **{item['prob_low']*100:.1f}–{item['prob_high']*100:.1f}%** · "
                f"Confianza **{sc}/100** · "
                f"Acuerdo **{item.get('agreement',0)*100:.0f}%** · {predictor_state}"
            )
            st.caption(detail_state)
            st.caption(item["reason"])
            risk,ricon=risk_profile_v72(item)
            st.caption(f"{ricon} Riesgo {risk} · {item.get('reason','')}")

        if analysis_summary["near"]:
            st.markdown("### 🟡 Cerca de calificar")
            st.caption("Estos mercados NO pasaron el filtro, pero quedaron relativamente cerca.")
            for j,item in enumerate(analysis_summary["near"],1):
                reason_parts=[]
                if item.get("prob_low",item["prob"])<.54:
                    reason_parts.append(f"conservadora {item.get('prob_low',item['prob'])*100:.1f}% < 54%")
                if item["confidence_score"]<48:
                    reason_parts.append(f"confianza {item['confidence_score']}/100 < 48")
                st.write(
                    f"**{j}. {item['label']}** — Central {item['prob']*100:.1f}% | "
                    f"Rango {item.get('prob_low',item['prob'])*100:.1f}–{item.get('prob_high',item['prob'])*100:.1f}% | "
                    f"Confianza {item['confidence_score']}/100"
                )
                st.caption("No calificó por: " + " · ".join(reason_parts))

    if st.session_state.get("v653_analysis_ready",False) and ranked_auto:
        if st.button("💾 Guardar este análisis en historial",key="save_v6_analysis"):
            stamp=now_cdmx().strftime("%Y-%m-%d %H:%M:%S CDMX")
            for item in ranked_auto:
                st.session_state["v653_history"].append({
                    "timestamp":stamp,
                    "date":selected_date.isoformat(),
                    "game":game["label"],
                    "market":item["label"],
                    "prob_central":round(item["prob"],4),
                    "prob_low":round(item.get("prob_low",item["prob"]),4),
                    "prob_high":round(item.get("prob_high",item["prob"]),4),
                    "confidence":item["confidence_score"],
                    "agreement":round(item.get("agreement",0),4),
                    "category":item.get("category",""),
                    "confirmed":item.get("confirmed",False),
                    "result":""
                })
            st.success("Análisis guardado en esta sesión.")

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

        st.write("**Qué hace V7 diferente**")
        st.write("• Regresa muestras pequeñas hacia la media MLB.")
        st.write("• Mezcla modelo conservador, balanceado y sensible a forma reciente.")
        st.write("• Simula incertidumbre del parámetro de carreras, no solo resultados Poisson fijos.")
        st.write("• Penaliza falta de lineup, mercados volátiles y desacuerdo entre modelos.")
        st.write("• Props de hits usan aproximación binomial con tasa regresada; Ks usan mezcla gamma-Poisson.")

        st.write("**Bullpen / staff proxy V5.1**")
        bp1,bp2=st.columns(2)
        with bp1:
            if away_staff:
                st.caption(
                    f"{game['away_abbr']}: ERA {away_staff['era']:.2f} · WHIP {away_staff['whip']:.2f} · "
                    f"RA/G L10 {away_staff['recent_ra_pg']:.2f} · RA/G L3 {away_staff.get('recent3_ra_pg',away_staff['recent_ra_pg']):.2f} · "
                    f"fatiga base {away_staff.get('fatigue_index',0)*100:.0f}% · "
                    f"carga real reciente {away_staff.get('workload_fatigue',0)*100:.0f}%"
                )
        with bp2:
            if home_staff:
                st.caption(
                    f"{game['home_abbr']}: ERA {home_staff['era']:.2f} · WHIP {home_staff['whip']:.2f} · "
                    f"RA/G L10 {home_staff['recent_ra_pg']:.2f} · RA/G L3 {home_staff.get('recent3_ra_pg',home_staff['recent_ra_pg']):.2f} · "
                    f"fatiga base {home_staff.get('fatigue_index',0)*100:.0f}% · "
                    f"carga real reciente {home_staff.get('workload_fatigue',0)*100:.0f}%"
                )

        st.write("**Datos disponibles**")
        for note in quality_notes:
            st.write(note)

with tabExpress:
    st.subheader("⚡ Express — qué puedo apostar AHORA")
    st.caption("Cada búsqueda vuelve a revisar la jornada. Los juegos que ya empezaron se excluyen automáticamente.")
    e1,e2,e3,e4=st.columns(4)
    target_n=int(e1.number_input("¿Cuántas apuestas buscas?",min_value=1,max_value=30,value=10,step=1))
    lineup_mode=e2.selectbox("Lineups",["Solo completos","Completos o pendientes"],index=0)
    use_odds=e3.toggle("Usar momios de referencia",value=False,help="Apagado: elige por probabilidad, confianza y riesgo. Encendido: además valida el precio de mercado y consume créditos.")
    diversify=e4.checkbox("Diversificación automática",value=True,help="Ranking por familias. Pitcher Ks ya no puede monopolizar el Top.")
    allowed_groups=st.multiselect("Mercados a incluir",["F5 / juego","Full Game","Pitcher props","Batter props"],default=["F5 / juego","Full Game","Pitcher props","Batter props"],help="F5 / juego incluye totales F5 y ganador F5. Full Game incluye totales y ganador Moneyline del partido completo. Puedes quitar cualquier familia.")
    max_per_game=int(st.number_input("Máximo de selecciones por partido",min_value=1,max_value=3,value=1,step=1,help="Permite hasta 1, 2 o 3 selecciones del mismo juego dentro del Top."))
    show_risky=st.toggle("Si no hay suficientes verdes, mostrar las mejores alternativas con riesgo",value=True,help="No las marca como seguras: simplemente muestra las de mayor probabilidad disponible con su nivel de riesgo y confianza.")
    st.caption("🎯 Primero se rankea cada familia por separado y después se arma el Top. Si faltan picks verdes, puedes ver el mejor Top disponible aunque incluya riesgo.")

    nowx=now_cdmx()
    future_games=[g for g in games if game_is_pregame(g,nowx)]
    started_count=len(games)-len(future_games)
    st.caption(f"🕒 {nowx.strftime('%I:%M:%S %p')} CDMX · {len(future_games)} partidos aún no iniciados · {started_count} iniciados/finalizados excluidos")

    if st.button("⚡ Buscar mejores oportunidades ahora",type="primary",use_container_width=True,key="v72_express_run"):
        eligible=[]; complete=0; pending=0
        pre=st.progress(0,text="1/2 Revisando horarios y lineups...")
        for i,g in enumerate(future_games):
            raw=get_lineups(g["game_pk"])
            both=len(raw.get("away",[]))>=9 and len(raw.get("home",[]))>=9
            complete+=int(both); pending+=int(not both)
            if lineup_mode=="Solo completos" and not both:
                pre.progress((i+1)/max(1,len(future_games)),text=f"Lineups {i+1}/{len(future_games)}")
                continue
            eligible.append(g)
            pre.progress((i+1)/max(1,len(future_games)),text=f"Lineups {i+1}/{len(future_games)}")
        pre.empty()
        st.session_state["v72_express_counts"]={"future":len(future_games),"complete":complete,"pending":pending,"eligible":len(eligible),"started":started_count,"time":nowx.strftime('%H:%M:%S')}

        allp=[]
        prog=st.progress(0,text="2/2 Analizando solo partidos elegibles...")
        for i,g in enumerate(eligible):
            try:
                picks,meta=analyze_game_express_v7(g,selected_date)
                allp.extend(picks)
            except Exception as ex:
                pass
            prog.progress((i+1)/max(1,len(eligible)),text=f"Analizados {i+1}/{len(eligible)}")
        prog.empty()

        enriched=[]
        for x in allp:
            y=dict(x); y["confidence_score"]=confidence_score(y)
            risk,ricon=risk_profile_v72(y); y["risk_label"]=risk; y["risk_icon"]=ricon
            enriched.append(y)
        # Safety-first pre-rank. Odds are completely optional.
        enriched=[z for z in enriched if market_group_v722(z) in set(allowed_groups)]
        enriched=sorted(enriched,key=lambda z:(z.get("prob_low",0),z.get("confidence_score",0)),reverse=True)
        prepool=enriched[:max(target_n*8,60)]

        usage={}
        if use_odds and odds_api_enabled() and prepool:
            prepool,usage=enrich_candidates_reference_odds(prepool,games)
            st.session_state["v72_odds_usage"]=usage
        for y in prepool:
            y["express_safety_score"]=express_safety_score_v721(y,use_odds=use_odds)
        qualified=[y for y in prepool if express_qualifies_v721(y,use_odds=use_odds)]
        qualified=sorted(qualified,key=lambda z:z.get("express_safety_score",-9),reverse=True)
        chosen=diversify_express_v721(qualified,target_n,max_per_game=max_per_game,automatic=diversify,allowed_groups=allowed_groups)
        chosen_ids={(z.get("game_pk"),z.get("label")) for z in chosen}
        near=[z for z in prepool if (z.get("game_pk"),z.get("label")) not in chosen_ids]
        near=sorted(near,key=lambda z:z.get("express_safety_score",-9),reverse=True)

        # V7.2.4 fallback: si el usuario pidió N y hay menos verdes, completa SOLO la visualización
        # con las mejores alternativas disponibles, respetando familias y máximo por partido.
        fallback=[]
        if show_risky and len(chosen)<target_n:
            needed=target_n-len(chosen)
            # Para mercados de juego prioriza además el lado ML con mayor probabilidad de cada partido.
            # Esto responde a: "entre los dos equipos, dime cuál tiene mayor probabilidad".
            ranked_near=sorted(near,key=lambda z:(z.get("prob_low",0),z.get("confidence_score",0),z.get("prob",0)),reverse=True)
            existing=list(chosen)
            game_counts={}
            for z in existing: game_counts[z.get("game")]=game_counts.get(z.get("game"),0)+1
            for z in ranked_near:
                if len(fallback)>=needed: break
                if game_counts.get(z.get("game"),0)>=max_per_game: continue
                fallback.append(z)
                game_counts[z.get("game")]=game_counts.get(z.get("game"),0)+1
        shown_all=chosen+fallback
        # Mejor ganador por partido (Full Game ML preferido; F5 ML si Full Game no está habilitado).
        winner_pool=[z for z in prepool if z.get("market_family") in {"fg_ml","f5_ml"}]
        best_winners=[]
        by_game={}
        for z in winner_pool:
            fam=z.get("market_family")
            # Respeta los mercados elegidos por el usuario.
            if fam=="fg_ml" and "Full Game" not in allowed_groups: continue
            if fam=="f5_ml" and "F5 / juego" not in allowed_groups: continue
            key=(z.get("game"),fam)
            if key not in by_game or z.get("prob",0)>by_game[key].get("prob",0): by_game[key]=z
        # Si hay Full Game, evita duplicar F5 del mismo juego en esta vista de ganador.
        games_with_fg={k[0] for k in by_game if k[1]=="fg_ml"}
        for (gm,fam),z in by_game.items():
            if fam=="f5_ml" and gm in games_with_fg: continue
            best_winners.append(z)
        best_winners=sorted(best_winners,key=lambda z:(z.get("prob_low",0),z.get("prob",0)),reverse=True)
        st.session_state["v724_best_winners"]=best_winners
        st.session_state["v7_express_results"]=chosen
        st.session_state["v724_express_fallback"]=fallback
        st.session_state["v723_express_near"]=near[:max(12,target_n*2)]
        st.session_state["v723_express_stats"]={"markets":len(allp),"prepool":len(prepool),"qualified":len(qualified),"shown":len(shown_all),"greens":len(chosen),"fallback":len(fallback)}
        st.session_state["v721_use_odds"]=use_odds
        st.session_state["v72_express_lineup_mode"]=lineup_mode
        st.session_state["v722_allowed_groups"]=allowed_groups
        st.session_state["v724_show_risky"]=show_risky

    counts=st.session_state.get("v72_express_counts")
    if counts:
        a,b,c,d=st.columns(4)
        a.metric("Elegibles analizados",counts["eligible"])
        b.metric("Lineup completo",counts["complete"])
        c.metric("Lineup pendiente",counts["pending"])
        d.metric("Ya iniciados",counts["started"])
        st.caption(f"Última búsqueda Express: {counts['time']} CDMX")

    if odds_api_enabled():
        usage=st.session_state.get("v72_odds_usage",{})
        rem=usage.get("remaining")
        if st.session_state.get("v721_use_odds",False):
            st.caption("🌐 Momios ACTIVADOS para esta búsqueda"+(f" · créditos restantes: {rem}" if rem not in (None,"None") else ""))
        else:
            st.caption("🧠 Búsqueda SIN momios: ranking por probabilidad + confianza + riesgo. No se gastaron créditos de odds en esta búsqueda.")
    else:
        st.caption("🧠 The Odds API no está configurada; Express puede funcionar sin momios usando probabilidad + confianza + riesgo.")

    express=st.session_state.get("v7_express_results",[])
    fallback=st.session_state.get("v724_express_fallback",[])
    display_express=express+fallback
    estats=st.session_state.get("v723_express_stats")
    if estats:
        q1,q2,q3,q4=st.columns(4)
        q1.metric("Mercados generados",estats.get("markets",0))
        q2.metric("Comparados",estats.get("prepool",0))
        q3.metric("Verdes / APOSTAR",estats.get("greens",estats.get("qualified",0)))
        q4.metric("Top mostrado",estats.get("shown",0))
    best_winners=st.session_state.get("v724_best_winners",[])
    if best_winners and ("Full Game" in st.session_state.get("v722_allowed_groups",[]) or "F5 / juego" in st.session_state.get("v722_allowed_groups",[])):
        with st.expander("🏆 Ganador con mayor probabilidad por partido — aunque no llegue a verde", expanded=False):
            st.caption("Aquí V7 compara los dos equipos y muestra el lado con mayor probabilidad del modelo. Si no alcanza nivel verde, se marca como riesgo y NO como apuesta segura.")
            for z in best_winners[:15]:
                rr,ri=risk_profile_v72(z)
                st.markdown(f"**{z.get('game','')} → {z.get('label','')}** · Central {z.get('prob',0)*100:.1f}% · Conservadora {z.get('prob_low',0)*100:.1f}% · Conf. {z.get('confidence_score',0)}/100 · {ri} {rr}")
    if display_express:
        if express:
            st.success(f"🟢 {len(express)} selecciones alcanzaron nivel APOSTAR.")
        if fallback:
            st.warning(f"🟡 Añadí {len(fallback)} alternativas de mayor probabilidad para completar el Top. Tienen más riesgo o menor confianza: no son equivalentes a un verde.")
        gd={}
        for _x in display_express:
            _g=market_group_v722(_x); gd[_g]=gd.get(_g,0)+1
        st.caption("Distribución del Top: " + " · ".join(f"{g}: {n}" for g,n in gd.items()))
        green_keys={(z.get("game_pk"),z.get("label")) for z in express}
        for i,x in enumerate(display_express,1):
            risk=x.get("risk_label") or risk_profile_v72(x)[0]; ricon=x.get("risk_icon") or risk_profile_v72(x)[1]
            is_green=(x.get("game_pk"),x.get("label")) in green_keys
            status_txt="🟢 APOSTAR" if is_green else "🟡 MAYOR PROBABILIDAD / CON RIESGO"
            with st.container(border=True):
                st.markdown(f"### {i}. {x['game']} · {x['label']}")
                st.caption(f"**{status_txt}**")
                m1,m2,m3,m4=st.columns(4)
                m1.metric("Prob. central",f"{x.get('prob',0)*100:.1f}%")
                m2.metric("Conservadora",f"{x.get('prob_low',0)*100:.1f}%")
                m3.metric("Confianza",f"{x.get('confidence_score',0)}/100")
                m4.metric("Riesgo",f"{ricon} {risk}")
                if x.get("line_repriced"):
                    st.caption(f"🔄 Línea de mercado detectada y recalculada: {float(x.get('original_model_line')):g} → {float(x.get('line')):g}.")
                if x.get("reference_odds"):
                    st.caption(f"🌐 Ref. {x['reference_odds']:.2f}x · mínimo modelo {x.get('reference_target_odds',x.get('model_target_odds',0)):.2f}x · EV conservador {x.get('reference_ev_cons',0)*100:+.1f}% · {x.get('reference_books',0)} casas")
                else:
                    st.caption(f"Momio mínimo orientativo ≈ {x.get('model_target_odds',0):.2f}x · esta selección fue elegida por probabilidad + confianza + riesgo; el precio no intervino en el ranking.")
                if x.get("reason"): st.caption("📌 "+x["reason"])

                # Inline line editor requested by the user: edit the recommendation itself, not a separate tab.
                if x.get("sample_values") is not None:
                    with st.expander("✏️ Draftea tiene otra línea / editar esta apuesta"):
                        c1,c2,c3=st.columns(3)
                        side=c1.selectbox("Lado",["over","under"],index=0 if x.get("side")=="over" else 1,format_func=lambda z:"Over / Más" if z=="over" else "Under / Menos",key=f"v72_side_{x['game_pk']}_{i}")
                        line=c2.number_input("Línea disponible en Draftea",value=float(x.get("line",.5)),step=.5,key=f"v72_line_{x['game_pk']}_{i}")
                        default_od=float(x.get("reference_odds") or 1.80)
                        od=c3.number_input("Momio Draftea",min_value=1.01,max_value=20.0,value=default_od,step=.01,format="%.2f",key=f"v72_odds_{x['game_pk']}_{i}")
                        rx=v7_reprice_line(x,line,side)
                        if rx:
                            pm=v7_price_metrics(rx,od); rr,ri=risk_profile_v72(rx)
                            z1,z2,z3,z4,z5=st.columns(5)
                            z1.metric("Nueva prob.",f"{rx['prob']*100:.1f}%")
                            z2.metric("Conservadora",f"{rx['prob_low']*100:.1f}%")
                            z3.metric("Momio mínimo",f"{pm['target']:.2f}x")
                            z4.metric("EV cons.",f"{pm['ev_cons']*100:+.1f}%")
                            z5.metric("Riesgo",f"{ri} {rr}")
                            icon="🟢" if pm["verdict"]=="APOSTAR" else "🟡" if pm["verdict"]=="CANDIDATO" else "⚪"
                            st.markdown(f"**{icon} {pm['verdict']} con la línea {line:g} @ {od:.2f}x**")
                            st.caption("La probabilidad fue recalculada para ESTA línea; nunca se reutiliza la probabilidad de la línea original.")
                            if st.button("✅ Usar esta línea y momio",key=f"v721_apply_{x['game_pk']}_{i}",use_container_width=True):
                                rx["draftea_odds"]=float(od)
                                rx["manual_line_edited"]=True
                                rx["manual_verdict"]=pm["verdict"]
                                rx["model_target_odds"]=pm["target"]
                                rx["risk_label"],rx["risk_icon"]=rr,ri
                                # Old reference quote may correspond to another line; do not carry it over as if it matched.
                                rx["reference_odds"]=None
                                rx["reference_ev_cons"]=None
                                old_key=(x.get("game_pk"),x.get("label"))
                                current=list(st.session_state.get("v7_express_results",[]))
                                fb=list(st.session_state.get("v724_express_fallback",[]))
                                replaced=False
                                for arr_name,arr in [("green",current),("fallback",fb)]:
                                    for kk,z in enumerate(arr):
                                        if (z.get("game_pk"),z.get("label"))==old_key:
                                            arr[kk]=rx; replaced=True; break
                                    if replaced: break
                                st.session_state["v7_express_results"]=current
                                st.session_state["v724_express_fallback"]=fb
                                st.success("Ajuste guardado. Evaluar momios usará esta línea y este momio de Draftea.")
                                st.rerun()
                    
    else:
        if estats:
            st.warning("No encontré candidatos utilizables con esos mercados/filtros. Si 'Mercados generados' es 0, hay un problema de generación de candidatos y no una ausencia real de juegos.")
        else:
            st.info("Ejecuta Express para ver el Top disponible en este momento.")

with tabParlay:
    st.subheader("🎟️ Constructor de Parlays — todos los juegos")
    base=st.session_state.get("v7_express_results",[])
    if not base:
        st.info("Primero ejecuta **Modo Express**. El parlay buscará entre todos esos juegos.")
    else:
        p1,p2,p3=st.columns(3)
        legs=int(p1.number_input("Selecciones",min_value=2,max_value=6,value=3,step=1))
        profile=p2.selectbox("Perfil",["Conservador","Balanceado","Agresivo"])
        different_games=p3.checkbox("Preferir juegos distintos",value=True)
        # Usa momio mínimo del modelo como placeholder editable; no afirma ser cuota de sportsbook.
        pool=sorted(base,key=lambda x:(x.get("prob_low",0),x.get("confidence_score",0)),reverse=True)[:12]
        if st.button("🎟️ Construir parlay",type="primary",key="v7_build_parlay"):
            best=None
            for combo in itertools.combinations(pool,min(legs,len(pool))):
                if different_games and len({x['game'] for x in combo})<len(combo): continue
                probs=[x.get("prob_low",x["prob"]) for x in combo]
                joint=float(np.prod(probs))
                odds=float(np.prod([x.get("reference_odds") or x.get("model_target_odds",1.01) for x in combo]))
                # Penaliza misma categoría/jugador y demasiadas piernas.
                subjects=[x.get("subject",x["label"]) for x in combo]
                corr_pen=.93 if len(subjects)!=len(set(subjects)) else 1.0
                score=joint*corr_pen*(1+min(odds,8)/30)
                if best is None or score>best[0]:best=(score,combo,joint,odds)
            st.session_state["v7_parlay"]=best
        best=st.session_state.get("v7_parlay")
        if best:
            _,combo,joint,odds=best
            st.markdown(f"### Parlay sugerido · {len(combo)} piernas")
            actual_odds=[]
            for i,x in enumerate(combo,1):
                c1,c2=st.columns([3,1])
                c1.write(f"**{i}. {x['game']} · {x['label']}** — conservadora {x.get('prob_low',x['prob'])*100:.1f}%")
                actual_odds.append(c2.number_input(f"Momio {i}",min_value=1.01,max_value=20.0,value=float(round(x.get('reference_odds') or x.get('model_target_odds',1.5),2)),step=.01,key=f"v7_parlay_odds_{i}_{x['label']}"))
            combined=float(np.prod(actual_odds))
            st.metric("Momio combinado",f"{combined:.2f}x")
            st.caption(f"Probabilidad conjunta conservadora aproximada (asumiendo independencia): {joint*100:.1f}%. No es un parlay 'seguro'; la dependencia entre mercados puede alterar esa cifra.")

with tab2:
    st.subheader("💵 Evaluar momios — usa exactamente lo que ajustaste en Express")
    express_eval=list(st.session_state.get("v7_express_results",[]))+list(st.session_state.get("v724_express_fallback",[]))
    source_is_express=bool(express_eval)
    source_candidates=express_eval if source_is_express else (ranked_auto if st.session_state.get("v653_analysis_ready",False) else [])

    if source_is_express:
        st.success("Usando el Top de Express. Si editaste una línea y pulsaste **Usar esta línea y momio**, aquí aparece ya ajustada.")
    else:
        st.caption("No hay Top Express activo; se usarán las oportunidades del partido individual analizado.")

    if not source_candidates:
        st.info("Primero ejecuta **⚡ Express** o analiza un partido individual.")
    else:
        labels=[x["label"] for x in source_candidates]
        selected=st.multiselect("¿Cuáles quieres revisar con el momio de Draftea?",labels,default=labels,key="v721_eval_selected")
        evaluated=[]
        for idx,label in enumerate(selected):
            item=next(x for x in source_candidates if x["label"]==label)
            default_od=float(item.get("draftea_odds") or item.get("reference_odds") or 1.80)
            target=1.05/max(float(item.get("prob_low",item.get("prob",.5))),.01)
            c1,c2,c3=st.columns([2.3,1,1])
            c1.write(f"**{item.get('game','')} · {label}**")
            c2.caption(f"Mínimo modelo ≈ {target:.2f}x")
            odds=c3.number_input(
                f"Momio Draftea {idx+1}",1.01,100.0,default_od,.01,
                format="%.2f",key=f"odd_v721_{idx}_{item.get('game_pk','x')}"
            )
            pm=v7_price_metrics(item,odds)
            risk,ri=risk_profile_v72(item)
            evaluated.append({**item,**pm,"odds":odds,"risk_label":risk,"risk_icon":ri})

        if evaluated:
            order={"APOSTAR":3,"CANDIDATO":2,"PASS":1}
            evaluated=sorted(evaluated,key=lambda x:(order.get(x.get("verdict"),0),x.get("prob_low",0),x.get("confidence_score",0)),reverse=True)
            st.markdown("### Resultado")
            best=evaluated[0]
            if best["verdict"]=="APOSTAR":
                st.success(f"🟢 MEJOR OPCIÓN ACTUAL: {best['game']} · {best['label']} @ {best['odds']:.2f}x")
            elif best["verdict"]=="CANDIDATO":
                st.warning(f"🟡 MEJOR CANDIDATO: {best['game']} · {best['label']} @ {best['odds']:.2f}x")
            else:
                st.info("⚪ PASS GENERAL — con estos momios ninguna selección compensa suficientemente el riesgo.")

            for i,x in enumerate(evaluated,1):
                icon="🟢" if x["verdict"]=="APOSTAR" else "🟡" if x["verdict"]=="CANDIDATO" else "⚪"
                edited=" · ✏️ línea ajustada en Express" if x.get("manual_line_edited") else ""
                st.write(
                    f"**{i}. {icon} {x['game']} · {x['label']} @ {x['odds']:.2f}x** — "
                    f"Central {x['prob']*100:.1f}% | Conservadora {x['prob_low']*100:.1f}% | "
                    f"Conf. {x.get('confidence_score',0)}/100 | Riesgo {x.get('risk_icon','')} {x.get('risk_label','')} | "
                    f"EV cons. {x['ev_cons']*100:+.1f}% | **{x['verdict']}**{edited}"
                )

            st.markdown("### 🧪 Guardar en Paper Betting")
            paper_labels=[f"{x['game']} · {x['label']}" for x in evaluated]
            paper_label=st.selectbox("Selección a registrar",paper_labels,key="paper_market_v721")
            paper_choice=evaluated[paper_labels.index(paper_label)]
            stake_mxn=st.number_input("Monto simulado (MXN)",min_value=5.0,max_value=10000.0,value=50.0,step=5.0,key="paper_stake_mxn_v721")
            pgame=next((g for g in games if int(g.get("game_pk",0))==int(paper_choice.get("game_pk",0))),None)
            plineups=get_lineups(paper_choice.get("game_pk")) if paper_choice.get("game_pk") else {"away":[],"home":[]}
            away_ok=len(plineups.get("away",[]))>=9; home_ok=len(plineups.get("home",[]))>=9; both_ok=away_ok and home_ok
            start_dt=game_start_cdmx(pgame) if pgame else None
            htg=((start_dt-now_cdmx()).total_seconds()/3600) if start_dt else None
            freeze_level="GREEN" if both_ok and (htg is None or htg>0) else "YELLOW"
            st.caption(f"Lineups al guardar: {'✅ completos' if both_ok else '⚠️ pendientes'} · estado {freeze_level}")

            if st.button("🧊 Congelar y registrar Paper Bet",type="primary",key="freeze_paper_v721"):
                pid=hashlib.sha1(f"{paper_choice.get('game_pk')}|{paper_choice['label']}|{now_cdmx().isoformat()}".encode()).hexdigest()[:10]
                rec={
                    "paper_id":pid,
                    "timestamp":now_cdmx().strftime("%Y-%m-%d %H:%M:%S CDMX"),
                    "freeze_time_iso":now_cdmx().isoformat(timespec="seconds"),
                    "hours_to_game_at_freeze":round(float(htg),2) if htg is not None else None,
                    "model_version":"V7.2.3",
                    "date":selected_date.isoformat(),
                    "game_pk":int(paper_choice.get("game_pk",0) or 0),
                    "game":paper_choice.get("game", pgame.get("label") if pgame else ""),
                    "game_time_cdmx":format_game_time_cdmx(pgame.get("game_time_local")) if pgame else "",
                    "away_abbr":pgame.get("away_abbr","") if pgame else "",
                    "home_abbr":pgame.get("home_abbr","") if pgame else "",
                    "market":paper_choice["label"],
                    "category":paper_choice.get("category",""),
                    "odds":round(float(paper_choice["odds"]),3),
                    "stake":round(float(stake_mxn/50.0),4),
                    "stake_mxn":round(float(stake_mxn),2),
                    "unit_value_mxn":50.0,
                    "prob_central":round(float(paper_choice["prob"]),5),
                    "prob_low":round(float(paper_choice.get("prob_low",paper_choice["prob"])),5),
                    "prob_high":round(float(paper_choice.get("prob_high",paper_choice["prob"])),5),
                    "confidence":int(paper_choice.get("confidence_score",confidence_score(paper_choice))),
                    "agreement":round(float(paper_choice.get("agreement",0)),5),
                    "confirmed":bool(paper_choice.get("confirmed",False)),
                    "away_lineup_confirmed":away_ok,
                    "home_lineup_confirmed":home_ok,
                    "both_lineups_confirmed":both_ok,
                    "away_lineup_count":len(plineups.get("away",[])),
                    "home_lineup_count":len(plineups.get("home",[])),
                    "data_quality":int(paper_choice.get("quality",0) or 0),
                    "readiness":freeze_level,
                    "readiness_level":freeze_level,
                    "freeze_type":"FINAL" if freeze_level=="GREEN" else "PRELIMINARY",
                    "status":"FROZEN",
                    "result":"PENDING",
                    "settlement_note":"",
                }
                st.session_state["v653_paper_bets"].append(rec)
                ok=persistent_upsert_paper_bet(rec)
                if ok:
                    st.success("🧊 Paper Bet guardada y persistida. Un F5/rerun ya no debe borrarla en la misma instancia; con Supabase también sobrevive reinicios/redeploys.")
                else:
                    st.warning("Se guardó en sesión, pero falló la persistencia externa/local.")


with tab4:
    st.subheader("🧪 Paper Betting — predicciones congeladas")
    st.caption(
        "Aquí no se mueve dinero. Guarda predicción + momio + confianza y después V7 intenta "
        "resolver el resultado automáticamente desde MLB."
    )

    upload=st.file_uploader("Restaurar un CSV de Paper Betting",type=["csv"],key="paper_upload_v65")
    if upload is not None and st.button("📥 Importar CSV",key="import_paper_v65"):
        try:
            decoded=upload.getvalue().decode("utf-8-sig")
            imported=[normalize_paper_row(dict(r)) for r in csv.DictReader(io.StringIO(decoded))]
            existing={r.get("paper_id") for r in st.session_state["v653_paper_bets"]}
            added=0
            for row in imported:
                if row.get("paper_id") not in existing:
                    st.session_state["v653_paper_bets"].append(row)
                    persistent_upsert_paper_bet(row)
                    added+=1
            st.success(f"Importados {added} registros nuevos.")
        except Exception as e:
            st.error(f"No pude importar el CSV: {e}")

    bets=st.session_state.get("v653_paper_bets",[])
    if not bets:
        st.info("Aún no hay Paper Bets. Ve a **Evaluar momios** y congela una predicción.")
    else:
        if st.button("🔄 Actualizar resultados desde MLB",type="primary",key="settle_paper_v65"):
            st.cache_data.clear()
            updated=0
            for rec in st.session_state["v653_paper_bets"]:
                if rec.get("result") in ("WON","LOST","PUSH"):
                    continue
                gr=get_game_result_v65(rec.get("game_pk"))
                if gr.get("final"):
                    verdict,note=settle_market_v65(rec,gr)
                    rec["result"]=verdict
                    rec["settlement_note"]=note
                    if verdict in ("WON","LOST","PUSH"):
                        rec["status"]="SETTLED"
                    persistent_upsert_paper_bet(rec)
                    updated+=1
            st.success(f"Revisé los registros. {updated} tuvieron partido final disponible.")

        st.write(f"Paper Bets registradas: **{len(bets)}**")
        for rec in reversed(bets[-30:]):
            icon={"WON":"✅","LOST":"❌","PUSH":"↩️","PENDING":"⏳","UNSUPPORTED":"⚠️"}.get(rec.get("result"),"⏳")
            st.write(
                f"**{icon} {rec.get('game')} · {rec.get('market')} @ {float(rec.get('odds',0)):.2f}x** — "
                f"{rec.get('game_time_cdmx','')} | apuesta ${float(rec.get('stake_mxn',0) or (float(rec.get('stake',1))*50)):,.2f} MXN | "
                f"conservadora {float(rec.get('prob_low',0))*100:.1f}% | "
                f"confianza {rec.get('confidence',0)}/100 | "
                f"{'🟢 FINAL' if rec.get('freeze_type')=='FINAL' else '🟡 PRELIMINAR'} | "
                f"lineups {'✅' if rec.get('both_lineups_confirmed') else '⚠️'} | "
                f"{rec.get('result','PENDING')}"
            )
            freeze_bits=[]
            if rec.get("timestamp"):
                freeze_bits.append(f"Congelada: {rec.get('timestamp')}")
            if rec.get("hours_to_game_at_freeze") not in (None,""):
                try:
                    freeze_bits.append(f"{float(rec.get('hours_to_game_at_freeze')):.1f} h antes del juego")
                except Exception:
                    pass
            freeze_bits.append(
                f"Lineups al congelar: {'confirmados' if rec.get('both_lineups_confirmed') else 'pendientes'}"
            )
            st.caption(" · ".join(freeze_bits))
            if rec.get("settlement_note"):
                st.caption(rec["settlement_note"])

        fields=[
            "paper_id","timestamp","freeze_time_iso","hours_to_game_at_freeze","model_version","date","game_pk","game","game_time_cdmx",
            "away_abbr","home_abbr","market","category","odds","stake","stake_mxn","unit_value_mxn",
            "prob_central","prob_low","prob_high","confidence","agreement","confirmed","away_lineup_confirmed","home_lineup_confirmed","both_lineups_confirmed","away_lineup_count","home_lineup_count",
            "data_quality","readiness","readiness_level","freeze_type","status","result","settlement_note"
        ]
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bets)
        st.download_button(
            "⬇️ Descargar Paper Betting CSV",
            data=output.getvalue().encode("utf-8"),
            file_name=f"mlb_v65_paper_betting_{date.today().isoformat()}.csv",
            mime="text/csv"
        )

        if st.button("🗑️ Limpiar Paper Betting",key="clear_paper_v65"):
            st.session_state["v653_paper_bets"]=[]
            persistent_delete_all_paper_bets()
            st.rerun()

with tab5:
    st.subheader("📊 Rendimiento y calibración")
    bets=st.session_state.get("v653_paper_bets",[])
    metrics=paper_metrics(bets)

    if metrics["decided"]==0:
        st.info("Todavía no hay suficientes Paper Bets resueltas para evaluar el modelo.")
        st.caption("El objetivo inicial es acumular un bloque sin cambiar el algoritmo, idealmente 100–200 predicciones.")
    else:
        m1,m2,m3,m4=st.columns(4)
        m1.metric("Resueltas",metrics["settled"])
        m2.metric("Acierto",f"{metrics['hit_rate']*100:.1f}%" if metrics["hit_rate"] is not None else "N/D")
        m3.metric("ROI paper",f"{metrics['roi']*100:+.1f}%" if metrics["roi"] is not None else "N/D")
        m4.metric("Ganancia paper",f"${metrics['profit']:+,.2f} MXN")

        m1,m2,m3,m4=st.columns(4)
        m1.metric("Ganadas",metrics["wins"])
        m2.metric("Perdidas",metrics["losses"])
        m3.metric("Push",metrics["pushes"])
        m4.metric("Brier Score",f"{metrics['brier']:.3f}" if metrics["brier"] is not None else "N/D")

        st.caption("Brier Score: menor es mejor. 0 sería predicción perfecta; por sí solo no basta, debe verse junto con calibración y tamaño de muestra.")
        if metrics["logloss"] is not None:
            st.caption(f"Log Loss actual: {metrics['logloss']:.3f}")

        st.markdown("### 🎯 Calibración")
        cal=calibration_rows(bets)
        if cal:
            st.table(cal)
        else:
            st.caption("Faltan registros en distintos rangos de probabilidad.")

        finals=[r for r in bets if r.get("freeze_type")=="FINAL" and r.get("result") in ("WON","LOST")]
        prelim=[r for r in bets if r.get("freeze_type")=="PRELIMINARY" and r.get("result") in ("WON","LOST")]
        st.markdown("### 🚦 Resultado según momento de congelación")
        pp1,pp2=st.columns(2)
        with pp1:
            if finals:
                fw=sum(r["result"]=="WON" for r in finals)
                st.metric("FINAL (semáforo verde)",f"{fw/len(finals)*100:.1f}% ({len(finals)} picks)")
            else:
                st.metric("FINAL (semáforo verde)","Sin muestra")
        with pp2:
            if prelim:
                pw=sum(r["result"]=="WON" for r in prelim)
                st.metric("PRELIMINAR (amarillo/rojo)",f"{pw/len(prelim)*100:.1f}% ({len(prelim)} picks)")
            else:
                st.metric("PRELIMINAR","Sin muestra")

        lineup_known=[r for r in bets if r.get("result") in ("WON","LOST") and "RECOVERED" not in str(r.get("model_version","")).upper()]
        with_lineup=[r for r in lineup_known if r.get("both_lineups_confirmed")]
        without_lineup=[r for r in lineup_known if not r.get("both_lineups_confirmed")]
        st.markdown("### 👥 Rendimiento según lineups al congelar")
        lp1,lp2=st.columns(2)
        with lp1:
            if with_lineup:
                ww=sum(r["result"]=="WON" for r in with_lineup)
                st.metric("Con lineups confirmados",f"{ww/len(with_lineup)*100:.1f}% ({len(with_lineup)} picks)")
            else:
                st.metric("Con lineups confirmados","Sin muestra")
        with lp2:
            if without_lineup:
                nw=sum(r["result"]=="WON" for r in without_lineup)
                st.metric("Con lineups pendientes",f"{nw/len(without_lineup)*100:.1f}% ({len(without_lineup)} picks)")
            else:
                st.metric("Con lineups pendientes","Sin muestra")

        st.markdown("### 🧩 Rendimiento por mercado")
        decided=[r for r in bets if r.get("result") in ("WON","LOST")]
        cats=sorted({r.get("category","Sin categoría") or "Sin categoría" for r in decided})
        rows=[]
        for cat in cats:
            group=[r for r in decided if (r.get("category","") or "Sin categoría")==cat]
            wins=sum(r["result"]=="WON" for r in group)
            conf_group=[r for r in group if "RECOVERED" not in str(r.get("model_version","")).upper() and float(r.get("confidence",0) or 0)>0]
            rows.append({
                "Mercado":cat,
                "N":len(group),
                "Acierto":f"{wins/len(group)*100:.1f}%" if group else "N/D",
                "Conf. media":f"{sum(float(r.get('confidence',0)) for r in conf_group)/len(conf_group):.0f}/100" if conf_group else "N/D"
            })
        if rows:
            st.table(rows)

        if metrics["decided"] < 30:
            st.warning("⚠️ Muestra todavía muy pequeña. No cambies pesos del modelo por estos primeros resultados.")
        elif metrics["decided"] < 100:
            st.warning("🟡 Ya hay información, pero todavía conviene completar al menos ~100 predicciones antes de recalibrar.")
        else:
            st.success("🟢 Ya existe una muestra útil para empezar una revisión formal de calibración por mercado.")


st.divider()
st.caption(
    "V7.2.3 ALPHA. Alta probabilidad no significa apuesta segura. El objetivo es elevar selección y calibración, no prometer un porcentaje fijo de aciertos. "
    "Paper Betting debe validar el modelo antes de aumentar riesgo real."
)