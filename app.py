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
HEADERS={"User-Agent":"MLB-Betting-Hub/7.6.4"}
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

def persistent_delete_paper_bet(paper_id):
    """Delete exactly one Paper Bet from local storage and Supabase when configured."""
    pid=str(paper_id or "")
    rows=[r for r in _local_load_paper_bets() if str(r.get("paper_id"))!=pid]
    local_ok=_local_write_paper_bets(rows)
    if not persistent_store_enabled():
        return local_ok
    try:
        url=_secret("SUPABASE_URL").rstrip("/")+"/rest/v1/mlb_paper_bets"
        r=requests.delete(url,params={"paper_id":f"eq.{pid}"},headers=_supabase_headers(True),timeout=12)
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
        "fg_ml":"h2h",
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
        fam=item.get("market_family")
        if fam=="fg_ml":
            # h2h outcomes are team names, not "home/away". Match the candidate team abbreviation.
            out_name=str(r.get("name") or "")
            mapped=ODDS_TEAM_ABBR.get(next((k for k in ODDS_TEAM_ABBR if k.lower()==out_name.lower()),""),"")
            if mapped!=str(item.get("subject") or ""): continue
        else:
            if side and r["name"]!=side:continue
            if subject and fam not in ("f5_total","fg_total"):
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
        stt=splits[0].get("stat",{})
        ip=float(stt.get("inningsPitched",0) or 0)
        so=float(stt.get("strikeOuts",0) or 0)
        bb=float(stt.get("baseOnBalls",0) or 0)
        hr=float(stt.get("homeRuns",0) or 0)
        gs=int(stt.get("gamesStarted",0) or 0)
        bf=float(stt.get("battersFaced",0) or 0)
        out={
            "player_id":player_id,"hand":hand,"era":float(stt.get("era",4.2) or 4.2),"whip":float(stt.get("whip",1.28) or 1.28),
            "innings":ip,"games_started":gs,"batters_faced":bf,
            "k9":so*9/ip if ip else 8.6,"bb9":bb*9/ip if ip else 3.2,"hr9":hr*9/ip if ip else 1.2,
            "strikeouts":so,"walks":bb,"home_runs":hr,
            "k_rate":so/bf if bf else None,
            "bb_rate":bb/bf if bf else None,
            "expected_ip":min(6.3,max(4.5,ip/gs if gs else 5.2)),
        }
        # V7.5: forma reciente del abridor, regresada después en pitcher_components.
        try:
            gl=_get(f"{BASE}/people/{player_id}/stats",{"stats":"gameLog","group":"pitching","season":season})
            grows=gl.get("stats",[{}])[0].get("splits",[]) if gl.get("stats") else []
            starts=[]
            for row in grows:
                ps=row.get("stat",{}) or {}
                if int(ps.get("gamesStarted",0) or 0)<=0: continue
                rip=float(ps.get("inningsPitched",0) or 0)
                if rip<=0: continue
                starts.append({
                    "ip":rip,"er":float(ps.get("earnedRuns",0) or 0),"so":float(ps.get("strikeOuts",0) or 0),
                    "bb":float(ps.get("baseOnBalls",0) or 0),"hr":float(ps.get("homeRuns",0) or 0),
                    "bf":float(ps.get("battersFaced",0) or 0)
                })
            recent=starts[-5:]
            if recent:
                rip=sum(x["ip"] for x in recent); rer=sum(x["er"] for x in recent)
                rso=sum(x["so"] for x in recent); rbb=sum(x["bb"] for x in recent); rhr=sum(x["hr"] for x in recent)
                out.update({
                    "recent_starts":len(recent),"recent_ip":rip,
                    "recent_era":rer*9/rip if rip else out["era"],
                    "recent_k9":rso*9/rip if rip else out["k9"],
                    "recent_bb9":rbb*9/rip if rip else out["bb9"],
                    "recent_hr9":rhr*9/rip if rip else out["hr9"],
                    "recent_ip_per_start":rip/len(recent)
                })
        except Exception:
            pass
        return out
    except Exception:return None

def attach_pitcher_statcast(pitcher,name,season):
    if not pitcher:return pitcher
    x=dict(pitcher)
    x["statcast"]=get_pitcher_statcast_profile(x.get("player_id"),name,season)
    return x

@st.cache_data(ttl=1800)
def get_team_form(team_id,target_date):
    target=datetime.strptime(target_date,"%Y-%m-%d").date()
    start=target.replace(month=3,day=20);end=target-timedelta(days=1)
    fb={"season_rpg":4.4,"recent_rpg":4.4,"season_rapg":4.4,"recent_rapg":4.4,
        "games":0,"recent_games":0,"wins":0,"losses":0,"win_pct":.5,"recent_win_pct":.5,
        "home_win_pct":.5,"away_win_pct":.5,"pythag_win_pct":.5,"run_diff_pg":0.0}
    if end<start:return fb
    try:
        data=_get(f"{BASE}/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat(),"gameType":"R"})
    except Exception:return fb
    rows=[]
    for d in data.get("dates",[]):
        for g in d.get("games",[]):
            if g.get("status",{}).get("abstractGameState")!="Final":continue
            teams=g.get("teams",{});a=teams.get("away",{});h=teams.get("home",{})
            if a.get("team",{}).get("id")==team_id:
                rf=a.get("score");ra=h.get("score");venue="away"
            elif h.get("team",{}).get("id")==team_id:
                rf=h.get("score");ra=a.get("score");venue="home"
            else:continue
            if rf is not None and ra is not None:
                rows.append((float(rf),float(ra),venue))
    if not rows:return fb
    recent=rows[-15:]
    wins=sum(1 for rf,ra,_ in rows if rf>ra); losses=len(rows)-wins
    rw=sum(1 for rf,ra,_ in recent if rf>ra)
    home=[r for r in rows if r[2]=="home"]; away=[r for r in rows if r[2]=="away"]
    hw=sum(1 for rf,ra,_ in home if rf>ra); aw=sum(1 for rf,ra,_ in away if rf>ra)
    rs=sum(rf for rf,_,_ in rows); rallow=sum(ra for _,ra,_ in rows)
    expn=1.83
    pyth=(rs**expn)/(rs**expn+rallow**expn) if (rs+rallow)>0 else .5
    return {
        "season_rpg":rs/len(rows),"recent_rpg":sum(x[0] for x in recent)/len(recent),
        "season_rapg":rallow/len(rows),"recent_rapg":sum(x[1] for x in recent)/len(recent),
        "games":len(rows),"recent_games":len(recent),"wins":wins,"losses":losses,
        "win_pct":wins/len(rows),"recent_win_pct":rw/len(recent),
        "home_win_pct":hw/len(home) if home else .5,"away_win_pct":aw/len(away) if away else .5,
        "pythag_win_pct":pyth,"run_diff_pg":(rs-rallow)/len(rows)
    }

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

# ================= V7.5 BASEBALL SAVANT / STATCAST =================
SAVANT="https://baseballsavant.mlb.com"

def _norm_person_name(x):
    return re.sub(r"[^a-z0-9]","",str(x or "").lower())

def _sv_num(row, aliases, default=None):
    if not row: return default
    low={str(k).strip().lower():v for k,v in row.items()}
    for a in aliases:
        v=low.get(str(a).lower())
        if v not in (None,"","--","null","None"):
            try:
                z=float(str(v).replace("%","").replace(",",""))
                if "%" in str(v): z/=100
                return z
            except Exception: pass
    return default

def _sv_text(row, aliases, default=""):
    if not row:return default
    low={str(k).strip().lower():v for k,v in row.items()}
    for a in aliases:
        v=low.get(str(a).lower())
        if v not in (None,""): return str(v)
    return default

@st.cache_data(ttl=21600,show_spinner=False)
def savant_csv_rows(url):
    """CSV público de Baseball Savant. Falla cerrado: [] y el modelo usa MLB StatsAPI."""
    try:
        r=requests.get(url,headers={"User-Agent":"Mozilla/5.0 MLB-Betting-Hub/7.5"},timeout=20)
        r.raise_for_status()
        txt=r.content.decode("utf-8-sig",errors="replace")
        return list(csv.DictReader(io.StringIO(txt)))
    except Exception:
        return []

@st.cache_data(ttl=21600,show_spinner=False)
def savant_tables(season):
    y=int(season)
    urls={
        "batted_batter":f"{SAVANT}/leaderboard/statcast?type=batter&year={y}&position=&team=&min=10&csv=true",
        "expected_batter":f"{SAVANT}/leaderboard/expected_statistics?type=batter&year={y}&position=&team=&filterType=pa&min=20&csv=true",
        "arsenal_batter":f"{SAVANT}/leaderboard/pitch-arsenal-stats?type=batter&pitchType=&year={y}&team=&min=20&csv=true",
        "batted_pitcher":f"{SAVANT}/leaderboard/statcast?type=pitcher&year={y}&position=&team=&min=10&csv=true",
        "expected_pitcher":f"{SAVANT}/leaderboard/expected_statistics?type=pitcher&year={y}&position=&team=&filterType=pa&min=20&csv=true",
        "arsenal_pitcher":f"{SAVANT}/leaderboard/pitch-arsenal-stats?type=pitcher&pitchType=&year={y}&team=&min=20&csv=true",
    }
    return {k:savant_csv_rows(u) for k,u in urls.items()}

def _sv_match_rows(rows, player_id=None, name=None):
    if not rows:return []
    pid=str(player_id or "")
    nn=_norm_person_name(name)
    out=[]
    id_alias=("player_id","playerid","mlbam_id","id","batter","pitcher")
    name_alias=("player_name","last_name, first_name","name","player")
    for r in rows:
        rid=_sv_text(r,id_alias,"")
        rn=_norm_person_name(_sv_text(r,name_alias,""))
        if (pid and rid and rid==pid) or (nn and rn and (rn==nn or nn in rn or rn in nn)):
            out.append(r)
    return out

def _sv_pct(v, default=None):
    if v is None:return default
    v=float(v)
    return v/100 if v>1.5 else v

def get_batter_statcast_profile(player_id,name,season):
    t=savant_tables(season)
    bb=_sv_match_rows(t.get("batted_batter"),player_id,name)
    ex=_sv_match_rows(t.get("expected_batter"),player_id,name)
    ar=_sv_match_rows(t.get("arsenal_batter"),player_id,name)
    b=bb[0] if bb else {}; e=ex[0] if ex else {}
    prof={
        "available":bool(bb or ex or ar),
        "avg_ev":_sv_num(b,["avg_hit_speed","avg_exit_velocity","exit_velocity_avg","launch_speed"]),
        "max_ev":_sv_num(b,["max_hit_speed","max_exit_velocity","max_ev"]),
        "launch_angle":_sv_num(b,["avg_hit_angle","launch_angle_avg","launch_angle"]),
        "barrel_pct":_sv_pct(_sv_num(b,["brl_percent","barrel_batted_rate","barrel_percent"])),
        "hard_hit_pct":_sv_pct(_sv_num(b,["hard_hit_percent","hard_hit_pct","hardhit_percent"])),
        "sweet_spot_pct":_sv_pct(_sv_num(b,["sweet_spot_percent","sweet_spot_pct"])),
        "xba":_sv_num(e,["est_ba","xba","estimated_ba_using_speedangle"]),
        "xslg":_sv_num(e,["est_slg","xslg"]),
        "xwoba":_sv_num(e,["est_woba","xwoba","estimated_woba_using_speedangle"]),
        "arsenal":{}
    }
    # outcome by pitch type. Uses pitch counts as weights when available.
    for r in ar:
        pt=_sv_text(r,["pitch_type","pitch_name","pitch"],"").strip()
        if not pt:continue
        prof["arsenal"][pt]={
            "pitches":_sv_num(r,["pitches","pitch_count","n"],1) or 1,
            "whiff":_sv_pct(_sv_num(r,["whiff_percent","whiff_pct","whiff"])),
            "woba":_sv_num(r,["woba","est_woba","xwoba"]),
            "slg":_sv_num(r,["slg","est_slg","xslg"]),
            "ba":_sv_num(r,["ba","avg","est_ba","xba"]),
            "run_value":_sv_num(r,["run_value_per_100","run_value","rv_100"]),
        }
    return prof

def get_pitcher_statcast_profile(player_id,name,season):
    t=savant_tables(season)
    bb=_sv_match_rows(t.get("batted_pitcher"),player_id,name)
    ex=_sv_match_rows(t.get("expected_pitcher"),player_id,name)
    ar=_sv_match_rows(t.get("arsenal_pitcher"),player_id,name)
    b=bb[0] if bb else {}; e=ex[0] if ex else {}
    prof={
        "available":bool(bb or ex or ar),
        "avg_ev_allowed":_sv_num(b,["avg_hit_speed","avg_exit_velocity","exit_velocity_avg"]),
        "barrel_pct_allowed":_sv_pct(_sv_num(b,["brl_percent","barrel_batted_rate","barrel_percent"])),
        "hard_hit_pct_allowed":_sv_pct(_sv_num(b,["hard_hit_percent","hard_hit_pct","hardhit_percent"])),
        "xba_allowed":_sv_num(e,["est_ba","xba"]),
        "xslg_allowed":_sv_num(e,["est_slg","xslg"]),
        "xwoba_allowed":_sv_num(e,["est_woba","xwoba"]),
        "arsenal":{}
    }
    for r in ar:
        pt=_sv_text(r,["pitch_type","pitch_name","pitch"],"").strip()
        if not pt:continue
        prof["arsenal"][pt]={
            "pitches":_sv_num(r,["pitches","pitch_count","n"],1) or 1,
            "whiff":_sv_pct(_sv_num(r,["whiff_percent","whiff_pct","whiff"])),
            "woba":_sv_num(r,["woba","est_woba","xwoba"]),
            "slg":_sv_num(r,["slg","est_slg","xslg"]),
            "ba":_sv_num(r,["ba","avg","est_ba","xba"]),
            "run_value":_sv_num(r,["run_value_per_100","run_value","rv_100"]),
        }
    vals=[x for x in prof["arsenal"].values() if x.get("whiff") is not None]
    if vals:
        den=sum(max(float(x.get("pitches",1)),1) for x in vals)
        prof["whiff_pct"]=sum(float(x["whiff"])*max(float(x.get("pitches",1)),1) for x in vals)/den
    else: prof["whiff_pct"]=None
    return prof

def pitch_arsenal_matchup_factor(batter_sc,pitcher_sc):
    """Weighted matchup from shared pitch types. Small bounded adjustment; never dominates base rates."""
    ba=(batter_sc or {}).get("arsenal",{}); pa=(pitcher_sc or {}).get("arsenal",{})
    common=[k for k in pa if k in ba]
    if not common:return 1.0,{"shared":0}
    weights=[]; scores=[]
    for k in common:
        pr=pa[k]; br=ba[k]; w=max(float(pr.get("pitches",1) or 1),1)
        sc=1.0
        if br.get("woba") is not None: sc*=clamp(float(br["woba"])/.315,.78,1.24)**.45
        if br.get("slg") is not None: sc*=clamp(float(br["slg"])/.410,.78,1.25)**.25
        if br.get("whiff") is not None: sc*=clamp(.245/max(float(br["whiff"]),.08),.80,1.22)**.22
        scores.append(sc);weights.append(w)
    f=sum(a*w for a,w in zip(scores,weights))/sum(weights)
    return clamp(f,.88,1.14),{"shared":len(common),"factor":f}

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
                    if ops>0:
                        split={
                            "ops":ops,"pa":pa,
                            "avg":_f(s.get("avg"),overall.get("avg",.250) if overall else .250),
                            "obp":_f(s.get("obp"),overall.get("obp",.320) if overall else .320),
                            "slg":_f(s.get("slg"),overall.get("slg",.400) if overall else .400),
                            "hits":int(s.get("hits",0) or 0),"hr":int(s.get("homeRuns",0) or 0),
                            "so":int(s.get("strikeOuts",0) or 0),"bb":int(s.get("baseOnBalls",0) or 0),
                        };break
                if split:break
    except Exception:split=None

    if not overall:
        return {"ops":.720,"avg":.250,"obp":.320,"slg":.400,"pa":0,"hits":0,"doubles":0,"triples":0,"hr":0,"runs":0,"rbi":0,"tb":0,"so":0,"bb":0,
                "hit_rate":.22,"single_rate":.145,"double_rate":.045,"triple_rate":.004,"hr_rate":.03,"tb_rate":.32,"hrr_rate":.42,"k_rate":.22,"bb_rate":.08,"iso":.150,
                "used_split":False,"stats_available":False}

    pa=max(overall["pa"],1)
    split_ok=bool(split and split["pa"]>=30)
    ops=split["ops"] if split_ok else overall["ops"]
    singles=max(0,overall["hits"]-overall["doubles"]-overall["triples"]-overall["hr"])
    split_factor=clamp_local((ops/max(overall.get("ops",LEAGUE_OPS),.300)),.82,1.18) if split_ok else 1.0
    return {**overall,"ops":ops,"platoon_ops":ops,"split_factor":split_factor,
            "split_avg":split.get("avg") if split_ok else overall.get("avg",.250),
            "split_obp":split.get("obp") if split_ok else overall.get("obp",.320),
            "split_slg":split.get("slg") if split_ok else overall.get("slg",.400),
            "iso":max(0.0,overall.get("slg",.400)-overall.get("avg",.250)),
            "hit_rate":overall["hits"]/pa,"single_rate":singles/pa,"double_rate":overall["doubles"]/pa,"triple_rate":overall["triples"]/pa,
            "hr_rate":overall["hr"]/pa,"tb_rate":overall["tb"]/pa,
            "hrr_rate":(overall["hits"]+overall["runs"]+overall["rbi"])/pa,"k_rate":overall["so"]/pa,"bb_rate":overall["bb"]/pa,
            "used_split":split_ok,"stats_available":True}

def enrich_lineup(lineup,season,opposing_hand):
    out=[]
    for item in lineup[:9]:
        base={**item,**get_hitter_stats(item["id"],season,opposing_hand)}
        base["statcast"]=get_batter_statcast_profile(item.get("id"),item.get("name"),season)
        out.append(base)
    return out

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
    sample=clamp(ip/90,.25,1.0)

    era=shrink_mean(float(p.get("era",LEAGUE_ERA)),ip,LEAGUE_ERA,45)
    whip=shrink_mean(float(p.get("whip",LEAGUE_WHIP)),ip,LEAGUE_WHIP,50)
    k9=shrink_mean(float(p.get("k9",LEAGUE_K9)),ip,LEAGUE_K9,45)
    bb9=shrink_mean(float(p.get("bb9",LEAGUE_BB9)),ip,LEAGUE_BB9,45)
    hr9=shrink_mean(float(p.get("hr9",LEAGUE_HR9)),ip,LEAGUE_HR9,50)

    # V7.5: últimos 5 starts aportan, pero siempre regresados a la muestra de temporada.
    rs=int(p.get("recent_starts",0) or 0)
    rip=float(p.get("recent_ip",0) or 0)
    if rs and rip:
        rera=shrink_mean(float(p.get("recent_era",era)),rip,era,28)
        rk9=shrink_mean(float(p.get("recent_k9",k9)),rip,k9,28)
        rbb9=shrink_mean(float(p.get("recent_bb9",bb9)),rip,bb9,28)
        rhr9=shrink_mean(float(p.get("recent_hr9",hr9)),rip,hr9,30)
        era=.78*era+.22*rera; k9=.80*k9+.20*rk9; bb9=.82*bb9+.18*rbb9; hr9=.84*hr9+.16*rhr9

    era_f=clamp(era/LEAGUE_ERA,.72,1.38)
    whip_f=clamp(whip/LEAGUE_WHIP,.78,1.30)
    k_f=clamp(LEAGUE_K9/max(k9,.1),.82,1.18)
    bb_f=clamp(bb9/LEAGUE_BB9,.78,1.24)
    hr_f=clamp(hr9/LEAGUE_HR9,.78,1.28)
    kbb=(k9/max(bb9,1.0))/(LEAGUE_K9/LEAGUE_BB9)
    kbb_f=clamp(1/max(kbb,.25),.84,1.18)

    conservative=.48*era_f+.24*whip_f+.10*k_f+.09*bb_f+.09*kbb_f
    balanced=.30*era_f+.23*whip_f+.17*k_f+.10*bb_f+.12*hr_f+.08*kbb_f
    skills=.16*era_f+.18*whip_f+.25*k_f+.14*bb_f+.18*hr_f+.09*kbb_f

    # V7.5 quality-of-contact allowed. Bounded and secondary to MLB production stats.
    sc=p.get("statcast") or {}
    sc_parts=[]
    if sc.get("xwoba_allowed") is not None: sc_parts.append(clamp(float(sc["xwoba_allowed"])/.315,.78,1.24))
    if sc.get("xslg_allowed") is not None: sc_parts.append(clamp(float(sc["xslg_allowed"])/.410,.78,1.26))
    if sc.get("barrel_pct_allowed") is not None: sc_parts.append(clamp(_sv_pct(sc["barrel_pct_allowed"])/.075,.72,1.34))
    if sc.get("hard_hit_pct_allowed") is not None: sc_parts.append(clamp(_sv_pct(sc["hard_hit_pct_allowed"])/.385,.82,1.22))
    sc_factor=sum(sc_parts)/len(sc_parts) if sc_parts else 1.0
    conservative=.92*conservative+.08*sc_factor
    balanced=.86*balanced+.14*sc_factor
    skills=.80*skills+.20*sc_factor

    def reg(f): return 1+(f-1)*sample
    return {
        "conservative":clamp(reg(conservative),.76,1.34),
        "balanced":clamp(reg(balanced),.74,1.36),
        "skills":clamp(reg(skills),.73,1.38),
        "sample":sample,"era_reg":era,"whip_reg":whip,"k9_reg":k9,"bb9_reg":bb9,"hr9_reg":hr9,
        "kbb_factor":kbb_f,"statcast_contact_factor":sc_factor,"statcast_available":bool(sc_parts)
    }

def lineup_component(lineup,confirmed):
    if not lineup:
        return {"factor":1.0,"quality":0.45,"ops":LEAGUE_OPS,"obp":.320,"slg":.400,"iso":.150,"k_rate":LEAGUE_K_PA,"bb_rate":.08}
    weights=[1.13,1.11,1.09,1.07,1.04,1.00,.97,.94,.91][:len(lineup)]
    vals=[]
    for p,w in zip(lineup,weights):
        if not p.get("stats_available"): continue
        pa=max(int(p.get("pa",0) or 0),0)
        vals.append((
            w,
            shrink_mean(float(p.get("ops",LEAGUE_OPS)),pa,LEAGUE_OPS,100),
            shrink_mean(float(p.get("obp",.320)),pa,.320,110),
            shrink_mean(float(p.get("slg",.400)),pa,.400,110),
            shrink_mean(float(p.get("iso",.150)),pa,.150,120),
            shrink_mean(float(p.get("k_rate",LEAGUE_K_PA)),pa,LEAGUE_K_PA,120),
            shrink_mean(float(p.get("bb_rate",.08)),pa,.08,120)
        ))
    if not vals:
        return {"factor":1.0,"quality":0.45,"ops":LEAGUE_OPS,"obp":.320,"slg":.400,"iso":.150,"k_rate":LEAGUE_K_PA,"bb_rate":.08}
    sw=sum(x[0] for x in vals)
    def wa(i): return sum(x[0]*x[i] for x in vals)/sw
    ops,obp,slg,iso,kr,bbr=[wa(i) for i in range(1,7)]
    composite=(.38*(ops/LEAGUE_OPS)+.22*(obp/.320)+.20*(slg/.400)+.10*(iso/.150)+.06*(LEAGUE_K_PA/max(kr,.05))+.04*(bbr/.08))
    # Statcast lineup contact quality: xwOBA/xSLG/xBA + barrels/hard-hit when available.
    sc_vals=[]
    for pp,w in zip(lineup,weights):
        sc=pp.get("statcast") or {}
        parts=[]
        if sc.get("xwoba") is not None: parts.append(clamp(float(sc["xwoba"])/.315,.80,1.22))
        if sc.get("xslg") is not None: parts.append(clamp(float(sc["xslg"])/.410,.80,1.25))
        if sc.get("xba") is not None: parts.append(clamp(float(sc["xba"])/.250,.84,1.18))
        if sc.get("barrel_pct") is not None: parts.append(clamp(_sv_pct(sc["barrel_pct"])/.075,.75,1.32))
        if sc.get("hard_hit_pct") is not None: parts.append(clamp(_sv_pct(sc["hard_hit_pct"])/.385,.84,1.20))
        if parts: sc_vals.append((w,sum(parts)/len(parts)))
    sc_factor=sum(w*v for w,v in sc_vals)/sum(w for w,_ in sc_vals) if sc_vals else 1.0
    composite=.84*composite+.16*sc_factor
    raw=clamp(composite,.82,1.20)
    strength=1+(raw-1)*.46
    if not confirmed: strength=1+(strength-1)*.42
    quality=.97 if confirmed and len(vals)>=8 else .70 if len(vals)>=6 else .52
    return {"factor":clamp(strength,.92,1.09),"quality":quality,"ops":ops,"obp":obp,"slg":slg,"iso":iso,"k_rate":kr,"bb_rate":bbr,
            "statcast_factor":sc_factor,"statcast_players":len(sc_vals)}

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
        "lineup_statcast_factor":round(lu.get("statcast_factor",1.0),3),
        "pitcher_statcast_factor":round(pit.get("statcast_contact_factor",1.0),3),
        "park_factor":round(park,3),
        "weather_factor":round(wf,3),
        "projected_runs":round(mean,3),
    }

def staff_proxy_factor(staff):
    if not staff:return 1.0
    era=shrink_mean(float(staff.get("era",LEAGUE_ERA)),80,LEAGUE_ERA,60)
    whip=shrink_mean(float(staff.get("whip",LEAGUE_WHIP)),80,LEAGUE_WHIP,60)
    recent=shrink_mean(float(staff.get("recent_ra_pg",LEAGUE_RPG)),10,LEAGUE_RPG,15)
    recent3=shrink_mean(float(staff.get("recent3_ra_pg",recent)),3,LEAGUE_RPG,7)
    fatigue=float(staff.get("fatigue_index",0.35))
    workload=float(staff.get("workload_fatigue",fatigue))
    factor=(.34*(era/LEAGUE_ERA)+.18*(whip/LEAGUE_WHIP)+.20*(recent/LEAGUE_RPG)+
            .08*(recent3/LEAGUE_RPG)+.08*(1+fatigue*.22)+.12*(1+workload*.34))
    return clamp(factor,.80,1.34)

def _record_strength(form,home_or_away=None):
    g=max(int(form.get("games",0) or 0),1)
    wp=shrink_mean(float(form.get("win_pct",.5)),g,.5,28)
    py=shrink_mean(float(form.get("pythag_win_pct",.5)),g,.5,24)
    rg=max(int(form.get("recent_games",0) or 0),1)
    rw=shrink_mean(float(form.get("recent_win_pct",.5)),rg,wp,18)
    venue=.5
    if home_or_away=="home": venue=float(form.get("home_win_pct",.5))
    elif home_or_away=="away": venue=float(form.get("away_win_pct",.5))
    venue=shrink_mean(venue,max(g/2,1),wp,20)
    return clamp(.42*wp+.36*py+.12*rw+.10*venue,.38,.62)

def project_full_game_ensemble_v73(away_f5,home_f5,away_form,home_form,away_staff,home_staff,
                                    away_pitcher=None,home_pitcher=None,away_lineup=None,home_lineup=None,
                                    lineups_confirmed=False,park_factor=1.0,weather=None):
    """V7.5 Game Prediction Engine.
    F5 carries starter/matchup information. Remaining innings use offense, bullpen quality/workload,
    expected starter length, lineup quality, park/weather and a modest home-field effect.
    """
    park=clamp(park_factor,.93,1.10); wf=weather_factor(weather)
    ao=offense_components(away_form); ho=offense_components(home_form)
    alu=lineup_component(away_lineup or [],lineups_confirmed); hlu=lineup_component(home_lineup or [],lineups_confirmed)
    home_bp=staff_proxy_factor(home_staff); away_bp=staff_proxy_factor(away_staff)
    aexp=float((away_pitcher or {}).get("expected_ip",5.2) or 5.2)
    hexp=float((home_pitcher or {}).get("expected_ip",5.2) or 5.2)
    # fraction of innings 6-9 expected to be handled by bullpen; longer starters reduce exposure.
    home_bp_share=clamp((9-hexp)/4,.62,1.08)
    away_bp_share=clamp((9-aexp)/4,.62,1.08)
    home_staff_mix=1+(home_bp-1)*home_bp_share
    away_staff_mix=1+(away_bp-1)*away_bp_share

    # Modest home-field effect: applied to run expectation, not as a forced winner probability.
    away_hfa=.992; home_hfa=1.024
    away_rest=BASE_REST*ao["balanced"]*home_staff_mix*alu["factor"]*park*wf*away_hfa
    home_rest=BASE_REST*ho["balanced"]*away_staff_mix*hlu["factor"]*park*wf*home_hfa
    away=clamp(away_f5+away_rest,1.35,9.5); home=clamp(home_f5+home_rest,1.35,9.5)

    # Scenario ensemble for calibration / agreement.
    scenarios=[]
    for oa,oh,scale in [(ao["conservative"],ho["conservative"],.97),(ao["balanced"],ho["balanced"],1.0),(ao["recent"],ho["recent"],1.03)]:
        ar=BASE_REST*oa*home_staff_mix*alu["factor"]*park*wf*away_hfa*scale
        hr=BASE_REST*oh*away_staff_mix*hlu["factor"]*park*wf*home_hfa*scale
        scenarios.append((clamp(away_f5+ar,1.2,10),clamp(home_f5+hr,1.2,10)))

    return away,home,{
        "away_remaining":round(away_rest,3),"home_remaining":round(home_rest,3),
        "away_staff_factor":round(away_bp,3),"home_staff_factor":round(home_bp,3),
        "away_bp_share":round(away_bp_share,3),"home_bp_share":round(home_bp_share,3),
        "away_lineup_factor":round(alu["factor"],3),"home_lineup_factor":round(hlu["factor"],3),
        "away_record_strength":round(_record_strength(away_form,"away"),3),
        "home_record_strength":round(_record_strength(home_form,"home"),3),
        "projected_total":round(away+home,3),"scenarios":scenarios
    }

def project_full_game_ensemble(away_f5,home_f5,away_form,home_form,away_staff,home_staff,park_factor=1.0,weather=None):
    # Backwards-compatible wrapper used by older sections.
    return project_full_game_ensemble_v73(away_f5,home_f5,away_form,home_form,away_staff,home_staff,
                                          park_factor=park_factor,weather=weather)

def _logit(p):
    p=clamp(float(p),.005,.995)
    return math.log(p/(1-p))

def _logistic(x): return 1/(1+math.exp(-x))

def _poisson_ml_prob(away_mu,home_mu,side="home"):
    # 9-inning score distribution; ties are split with a small home extra-inning edge.
    maxk=22
    ap=[math.exp(-away_mu)*(away_mu**k)/math.factorial(k) for k in range(maxk)]
    hp=[math.exp(-home_mu)*(home_mu**k)/math.factorial(k) for k in range(maxk)]
    ph=pa=pt=0.0
    for i,a in enumerate(ap):
        for j,h in enumerate(hp):
            pr=a*h
            if j>i: ph+=pr
            elif i>j: pa+=pr
            else: pt+=pr
    ph += pt*.535; pa += pt*.465
    den=ph+pa
    ph=ph/den if den else .5
    return ph if side=="home" else 1-ph

def full_game_ml_probability_v73(sim,side,away_form,home_form,away_staff,home_staff,fg_debug):
    raw=sim_ml_prob(sim,side)
    # Residual team-strength calibration: season record + Pythagorean + recent form.
    ars=_record_strength(away_form,"away"); hrs=_record_strength(home_form,"home")
    strength_diff=(hrs-ars)
    awork=float((away_staff or {}).get("workload_fatigue",.35)); hwork=float((home_staff or {}).get("workload_fatigue",.35))
    fatigue_edge=(awork-hwork)  # positive means home side faces the more fatigued bullpen
    home_logit=_logit(1-raw if side=="away" else raw)
    home_logit += 1.15*strength_diff + .16*fatigue_edge
    home_p=_logistic(home_logit)
    p=1-home_p if side=="away" else home_p

    scen=[]
    for am,hm in fg_debug.get("scenarios",[]):
        sp=_poisson_ml_prob(am,hm,side)
        # smaller residual correction in scenarios to avoid double counting.
        hp=1-sp if side=="away" else sp
        hp=_logistic(_logit(hp)+.75*strength_diff+.10*fatigue_edge)
        scen.append(1-hp if side=="away" else hp)
    return clamp(p,.03,.97),scen,{"raw":raw,"away_strength":ars,"home_strength":hrs,"fatigue_edge":fatigue_edge}

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

def _expected_pa_draws(rng, order, n):
    """Simula PA sin redondear siempre al mismo entero."""
    mu=expected_pa(order)
    lo=max(1,int(math.floor(mu))); hi=lo+1
    frac=mu-lo
    return lo + (rng.random(n)<frac).astype(int)

def _lineup_neighbors(lineup, order):
    """Contexto de corredores delante y bateadores detrás para R/RBI."""
    front=[x for x in lineup[:9] if x.get("order",9)<order]
    back=[x for x in lineup[:9] if x.get("order",1)>order]
    def avg_metric(rows,key,default):
        vals=[float(x.get(key,default)) for x in rows if x.get("stats_available")]
        return sum(vals)/len(vals) if vals else default
    traffic=avg_metric(front[-3:],"obp",.320)
    support=avg_metric(back[:3],"slg",.400)
    return traffic,support

def _market_quality_v74(fam, confirmed, sample, extras=1.0):
    base={"hits":88,"total_bases":84,"hrr":78,"home_run":70,"pitcher_k":86}.get(fam,80)
    if not confirmed: base-=16
    if sample<120: base-=8
    elif sample<220: base-=3
    return int(clamp(base*extras,42,96))

def build_prop_candidates_v7(away_pitcher,home_pitcher,away_pitcher_name,home_pitcher_name,
                             away_lineup,home_lineup,lineups_confirmed=False,park_factor=1.0,weather=None):
    """V7.5 Market Engine: distribución propia + Statcast/Savant cuando existe + matchup por arsenal."""
    props=[]
    wf=weather_factor(weather)
    park=clamp(float(park_factor or 1.0),.93,1.10)

    # ---------- Pitcher strikeouts: BF x K/PA, no Poisson simple ----------
    for name,p,opp_lineup in [
        (away_pitcher_name,away_pitcher,home_lineup),
        (home_pitcher_name,home_pitcher,away_lineup),
    ]:
        if not p: continue
        ip=max(float(p.get("innings",0) or 0),0)
        bf=max(float(p.get("batters_faced",0) or 0),0)
        exp_ip=shrink_mean(float(p.get("expected_ip",5.2)),max(p.get("games_started",0),1),5.15,12)
        if p.get("recent_ip_per_start"):
            exp_ip=.78*exp_ip+.22*shrink_mean(float(p["recent_ip_per_start"]),max(p.get("recent_starts",0),1),exp_ip,5)
        exp_ip=clamp(exp_ip,4.3,6.5)
        pk=shrink_mean(float(p.get("k_rate") or LEAGUE_K_PA),bf,LEAGUE_K_PA,190)
        pbb=shrink_mean(float(p.get("bb_rate") or .082),bf,.082,190)
        kbb_skill=clamp((pk/max(pbb,.025))/(LEAGUE_K_PA/.082),.78,1.28)
        rates=[];weights=[]
        lw=[1.12,1.10,1.08,1.05,1.02,1.00,.97,.94,.91]
        for idx,x in enumerate(opp_lineup[:9]):
            if x.get("stats_available"):
                w=lw[idx]
                rates.append(shrink_mean(float(x.get("k_rate",LEAGUE_K_PA)),max(x.get("pa",0),1),LEAGUE_K_PA,120)*w)
                weights.append(w)
        opp_k=sum(rates)/sum(weights) if weights else LEAGUE_K_PA
        opp_obp=np.mean([float(x.get("obp",.320)) for x in opp_lineup[:9] if x.get("stats_available")]) if opp_lineup else .320
        # BF/IP grows with traffic. 4.28 is a neutral baseline.
        bf_per_ip=clamp(4.28*(opp_obp/.320)**.28*(float(p.get("whip",LEAGUE_WHIP))/LEAGUE_WHIP)**.10,3.95,4.75)
        mean_bf=clamp(exp_ip*bf_per_ip,17,31)
        matchup=clamp((opp_k/LEAGUE_K_PA)**.72,.86,1.16)
        psc=(p or {}).get("statcast") or {}
        whiff=_sv_pct(psc.get("whiff_pct")) if psc.get("whiff_pct") is not None else None
        whiff_factor=clamp((whiff/.245)**.30,.90,1.12) if whiff else 1.0
        # lineup-level arsenal effect: weighted mean of batter-vs-pitcher pitch-type compatibility.
        am=[]
        for bx in opp_lineup[:9]:
            f,_=pitch_arsenal_matchup_factor(bx.get("statcast") or {},psc)
            am.append(f)
        arsenal_k_factor=clamp((2-(sum(am)/len(am)))**.24,.94,1.07) if am else 1.0
        kprob=clamp(pk*matchup*(kbb_skill**.13)*whiff_factor*arsenal_k_factor,.12,.41)
        confirmed=len(opp_lineup)>=9 and lineups_confirmed
        rng=np.random.default_rng(stable_seed(name,"K-V74"))
        n=18000
        # latent innings/BF uncertainty and binomial strikeout process.
        bf_sd=1.8 if confirmed else 2.8
        bfs=np.clip(np.rint(rng.normal(mean_bf,bf_sd,n)),12,34).astype(int)
        latent_k=np.clip(rng.normal(kprob,.018 if confirmed else .030,n),.08,.44)
        ks=np.array([rng.binomial(int(b),float(kp)) for b,kp in zip(bfs,latent_k)])
        q=_market_quality_v74("pitcher_k",confirmed,bf)
        for line in [2.5,3.5,4.5,5.5,6.5,7.5]:
            for side,word in [("over","Over"),("under","Under")]:
                prob=_sample_prob(ks,line,side); lo,hi=_bands_from_sample_prob(prob,confirmed,"medium")
                props.append({"category":"Pitcher Ks","label":f"{name} {word} {line:g} K",
                    "prob":prob,"prob_low":lo,"prob_high":hi,"agreement":.90 if confirmed else .70,
                    "quality":q,"confirmed":confirmed,"volatility":"medium","market_family":"pitcher_k",
                    "side":side,"line":line,"subject":name,"sample_values":ks,
                    "reason":(f"V7.5 K Engine · BF ~{mean_bf:.1f} · K/PA {pk*100:.1f}% · K% lineup {opp_k*100:.1f}% · IP ~{exp_ip:.1f}" + (f" · Whiff Statcast {whiff*100:.1f}% · arsenal x{arsenal_k_factor:.2f}." if whiff is not None else " · Savant no disponible: fallback MLB."))})

    # ---------- Batter markets: one correlated PA simulation ----------
    def hitters(lineup, opposing_pitcher):
        opp_hr9=float((opposing_pitcher or {}).get("hr9",LEAGUE_HR9) or LEAGUE_HR9)
        opp_whip=float((opposing_pitcher or {}).get("whip",LEAGUE_WHIP) or LEAGUE_WHIP)
        pitcher_hr_factor=clamp((opp_hr9/LEAGUE_HR9)**.34,.82,1.24)
        traffic_pitch_factor=clamp((opp_whip/LEAGUE_WHIP)**.20,.90,1.12)
        for p in lineup[:9]:
            if not p.get("stats_available"): continue
            sample=max(int(p.get("pa",0) or 0),0)
            confirmed=lineups_confirmed
            rng=np.random.default_rng(stable_seed(p['name'],"BAT-V74")); n=18000
            pa_draw=_expected_pa_draws(rng,p["order"],n)
            max_pa=int(pa_draw.max())
            split_adj=clamp(float(p.get("split_factor",1.0)),.84,1.16)
            bsc=p.get("statcast") or {}; psc=(opposing_pitcher or {}).get("statcast") or {}
            arsenal_factor,arsenal_meta=pitch_arsenal_matchup_factor(bsc,psc)
            xba=bsc.get("xba"); xslg=bsc.get("xslg"); xwoba=bsc.get("xwoba")
            barrel=_sv_pct(bsc.get("barrel_pct")) if bsc.get("barrel_pct") is not None else None
            hardhit=_sv_pct(bsc.get("hard_hit_pct")) if bsc.get("hard_hit_pct") is not None else None
            ev=bsc.get("avg_ev")
            contact_factor=1.0
            if xba is not None: contact_factor*=clamp(float(xba)/.250,.84,1.16)**.35
            if hardhit is not None: contact_factor*=clamp(float(hardhit)/.385,.82,1.20)**.20
            power_sc=1.0
            if xslg is not None: power_sc*=clamp(float(xslg)/.410,.78,1.28)**.35
            if barrel is not None: power_sc*=clamp(float(barrel)/.075,.70,1.45)**.30
            if ev is not None: power_sc*=clamp(float(ev)/88.5,.92,1.10)**.30
            iso=shrink_mean(float(p.get("iso",.150)),sample,.150,150)
            slg=shrink_mean(float(p.get("slg",.400)),sample,.400,140)
            obp=shrink_mean(float(p.get("obp",.320)),sample,.320,140)
            bb_rate=shrink_mean(float(p.get("bb_rate",.08)),sample,.08,150)

            # Component rates. Extra-base mix receives more ISO/SLG influence than simple hits.
            pr1=shrink_mean(float(p.get("single_rate",.145)),sample,.145,150)*split_adj**.45*contact_factor*.55+shrink_mean(float(p.get("single_rate",.145)),sample,.145,150)*.45
            pr2=shrink_mean(float(p.get("double_rate",.045)),sample,.045,175)*clamp((iso/.150)**.28,.80,1.28)*split_adj**.38*power_sc**.35*arsenal_factor**.28
            pr3=shrink_mean(float(p.get("triple_rate",.004)),sample,.004,260)
            pitcher_barrel=(psc or {}).get("barrel_pct_allowed")
            barrel_allow_factor=clamp((_sv_pct(pitcher_barrel)/.075)**.22,.84,1.20) if pitcher_barrel is not None else 1.0
            hr_context=clamp((iso/.150)**.30*(slg/.400)**.14*pitcher_hr_factor*(park**.55)*(wf**.65)*power_sc*.72+0.28, .58,1.78)
            hr_context*=barrel_allow_factor*arsenal_factor**.35
            pr4=shrink_mean(float(p.get("hr_rate",LEAGUE_HR_PA)),sample,LEAGUE_HR_PA,210)*split_adj**.40*hr_context
            prbb=clamp(bb_rate*clamp((obp/.320)**.18,.90,1.12),.025,.19)
            # Normalize if total on-base outcomes become unrealistic.
            hit_sum=pr1+pr2+pr3+pr4
            if hit_sum>.42:
                sc=.42/hit_sum; pr1*=sc;pr2*=sc;pr3*=sc;pr4*=sc
            prbb=min(prbb,.58-(pr1+pr2+pr3+pr4))
            probs=np.array([max(.20,1-(prbb+pr1+pr2+pr3+pr4)),prbb,pr1,pr2,pr3,pr4],dtype=float)
            probs=probs/probs.sum() # out, BB, 1B, 2B, 3B, HR
            draws=rng.choice(6,size=(n,max_pa),p=probs)
            active=np.arange(max_pa)[None,:] < pa_draw[:,None]
            draws=np.where(active,draws,-1)
            hits=np.sum((draws>=2)&active,axis=1)
            tbs=np.sum(np.where(draws==2,1,np.where(draws==3,2,np.where(draws==4,3,np.where(draws==5,4,0)))),axis=1)
            hrs=np.sum(draws==5,axis=1)

            # HRR: correlated with actual simulated events + lineup traffic/support.
            traffic,support=_lineup_neighbors(lineup,p["order"])
            traffic=clamp(traffic*traffic_pitch_factor,.270,.390)
            support=clamp(support,.320,.520)
            reached=((draws>=1)&active)
            extra_base=((draws>=3)&active)
            homer=(draws==5)
            # Run probability after reaching base; HR always scores.
            run_p=clamp(.34*(support/.400),.22,.52)
            run_rand=rng.random((n,max_pa))
            runs=np.sum(homer | (reached & ~homer & (run_rand<run_p)),axis=1)
            # RBI traffic: baseline runners in scoring position plus larger reward for XBH/HR.
            base_rbi=clamp(.105*(traffic/.320),.065,.165)
            rbi_p=np.where(homer,.92,np.where(extra_base,clamp(base_rbi*1.85,.10,.34),base_rbi))
            rbi_events=(rng.random((n,max_pa))<rbi_p)&(draws>=2)&active
            rbi=np.sum(rbi_events,axis=1)+hrs  # HR guarantees at least self-RBI; proxy may undercount multi-run HRs.
            hrr=hits+runs+rbi

            specs=[
                ("Hits","hits",hits,[.5,1.5,2.5],"low"),
                ("Total Bases","total_bases",tbs,[.5,1.5,2.5,3.5],"medium"),
                ("HRR","hrr",hrr,[.5,1.5,2.5,3.5],"medium"),
                ("Home Run","home_run",hrs,[.5],"high"),
            ]
            for cat,fam,vals,lines,vol in specs:
                q=_market_quality_v74(fam,confirmed,sample,1.0)
                for line in lines:
                    for side,word in [("over","Over"),("under","Under")]:
                        prob=_sample_prob(vals,line,side);lo,hi=_bands_from_sample_prob(prob,confirmed,vol)
                        props.append({"category":cat,"label":f"{p['name']} {word} {line:g} {cat}",
                            "prob":prob,"prob_low":lo,"prob_high":hi,"agreement":.92 if confirmed else .72,
                            "quality":q,"confirmed":confirmed,"volatility":vol,"market_family":fam,"side":side,
                            "line":line,"subject":p['name'],"sample_values":vals,
                            "reason":f"V7.5 {cat} Engine · PA ~{expected_pa(p['order']):.2f} · split x{split_adj:.2f} · ISO {iso:.3f} · OBP {obp:.3f} · arsenal x{arsenal_factor:.2f}" + (f" · xBA {float(xba):.3f} · xSLG {float(xslg):.3f} · Barrel {float(barrel)*100:.1f}% · Hard-Hit {float(hardhit)*100:.1f}%." if xba is not None and xslg is not None and barrel is not None and hardhit is not None else " · Savant parcial/no disponible: fallback MLB + parque/clima." )})
    hitters(away_lineup,home_pitcher); hitters(home_lineup,away_pitcher)
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

def market_reliability_v74(item):
    """Score de confiabilidad por mercado; no reemplaza probabilidad, evita tratar todos igual."""
    fam=item.get("market_family","")
    base={"fg_ml":.96,"f5_total":.94,"fg_total":.90,"pitcher_k":.88,"hits":.86,
          "total_bases":.81,"hrr":.75,"home_run":.64}.get(fam,.80)
    if not item.get("confirmed",False): base-=.10
    width=max(0,float(item.get("prob_high",item.get("prob",.5)))-float(item.get("prob_low",item.get("prob",.5))))
    base-=min(.12,width*.45)
    q=float(item.get("quality",70))/100
    return int(round(clamp((.72*base+.28*q)*100,35,98)))

def _paper_market_family(rec):
    cat=str(rec.get("category","")).lower(); market=str(rec.get("market","")).lower()
    if "full game" in market and "ml" in market:return "fg_ml"
    if cat=="f5" or market.startswith("f5 "):return "f5_total"
    if "full game" in market:return "fg_total"
    if "pitcher" in cat or " k" in market:return "pitcher_k"
    if "total bases" in cat or "total bases" in market:return "total_bases"
    if "hrr" in cat or "hrr" in market:return "hrr"
    if "home run" in cat or "home run" in market:return "home_run"
    if "hits" in cat or " hits" in market:return "hits"
    return cat

def market_calibration_v75(fam):
    """Empirical calibration only after enough genuine settled paper bets. Strong shrinkage prevents chasing noise."""
    try: rows=st.session_state.get("v653_paper_bets",[])
    except Exception: rows=[]
    xs=[]
    for r in rows:
        if r.get("result") not in ("WON","LOST"):continue
        if "RECOVERED" in str(r.get("model_version","")).upper():continue
        if _paper_market_family(r)!=fam:continue
        try:p=float(r.get("prob_low") or r.get("prob_central") or 0)
        except:p=0
        if .05<p<.95: xs.append((p,1.0 if r.get("result")=="WON" else 0.0))
    n=len(xs)
    if n<20:return {"active":False,"n":n,"delta":0.0,"observed":None,"predicted":None}
    pred=sum(x[0] for x in xs)/n; obs=sum(x[1] for x in xs)/n
    # prior equivalent to 60 picks: gradual, bounded correction ±4 pp.
    raw=(obs-pred)*n/(n+60)
    delta=clamp(raw,-.04,.04)
    return {"active":True,"n":n,"delta":delta,"observed":obs,"predicted":pred}

def apply_market_calibration_v75(item):
    x=dict(item); fam=x.get("market_family","")
    cal=market_calibration_v75(fam)
    x["calibration_v75"]=cal
    if cal.get("active"):
        d=float(cal.get("delta",0))
        x["prob_raw"]=x.get("prob")
        x["prob"]=clamp(float(x.get("prob",.5))+d,.01,.99)
        x["prob_low"]=clamp(float(x.get("prob_low",x["prob"]))+d,.01,.99)
        x["prob_high"]=clamp(float(x.get("prob_high",x["prob"]))+d,.01,.99)
    return x

def bet_quality_score_v75(item,use_odds=False):
    low=float(item.get("prob_low",item.get("prob",.5)))
    conf=float(item.get("confidence_score",confidence_score(item)))/100
    rel=float(item.get("market_reliability",market_reliability_v74(item)))/100
    data=float(item.get("data_quality",item.get("quality",65)))/100
    width=max(0,float(item.get("prob_high",item.get("prob",.5)))-float(item.get("prob_low",item.get("prob",.5))))
    confirmed=1.0 if item.get("confirmed") else .82
    sc_bonus=.0
    reason=str(item.get("reason",""))
    if "xBA" in reason or "Whiff Statcast" in reason: sc_bonus=.025
    score=(low*.45+conf*.18+rel*.17+data*.10+confirmed*.10-width*.12+sc_bonus)
    if use_odds and item.get("reference_odds"):
        score+=max(-.025,min(.04,float(item.get("reference_ev_cons",0) or 0)*.06))
    return int(round(clamp(score*100,0,99)))

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

    # V7.6.2: prefer structured market metadata. This keeps Paper Betting resolvable
    # even after the user edits a line/side in Express or Parlays.
    fam=str(record.get("market_family","") or "")
    side=str(record.get("side","") or "").lower()
    try: structured_line=float(record.get("line")) if record.get("line") not in (None,"") else None
    except Exception: structured_line=None
    subject=str(record.get("subject","") or "")
    if fam=="f5_total" and structured_line is not None and side in {"over","under"}:
        if not result.get("complete_f5"):
            return "UNSUPPORTED","No hay 5 entradas completas"
        total=result["f5_away"]+result["f5_home"]
        return compare_total(total,structured_line,side),f"F5 terminó {result['f5_away']}-{result['f5_home']} (total {total})"
    if fam=="fg_total" and structured_line is not None and side in {"over","under"}:
        total=result["away_runs"]+result["home_runs"]
        return compare_total(total,structured_line,side),f"Final {result['away_runs']}-{result['home_runs']} (total {total})"
    if fam=="fg_ml":
        team=subject or (market.split()[0] if market else "")
        if result["away_runs"]==result["home_runs"]:
            return "PUSH","Juego empatado"
        winner=away if result["away_runs"]>result["home_runs"] else home
        return ("WON" if team==winner else "LOST"),f"Final {away} {result['away_runs']} - {home} {result['home_runs']}"
    if fam in {"pitcher_k","hits","total_bases","hrr","home_run"} and structured_line is not None and side in {"over","under"}:
        stat=(result.get("player_stats") or {}).get(subject)
        if stat is None:
            return "UNSUPPORTED",f"No encontré stats de {subject or 'jugador'}"
        field={"pitcher_k":"strikeOutsPitching","hits":"hits","total_bases":"totalBases","home_run":"homeRuns"}.get(fam)
        if fam=="hrr": value=int(stat.get("hits",0))+int(stat.get("runs",0))+int(stat.get("rbi",0))
        else: value=int(stat.get(field,0))
        lbl={"pitcher_k":"K","hits":"hits","total_bases":"TB","hrr":"H+R+RBI","home_run":"HR"}.get(fam,fam)
        return compare_total(value,structured_line,side),f"{subject}: {value} {lbl}"

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
    for _json_field,_target in [("legs_json","legs"),("leg_results_json","leg_results")]:
        if row.get(_json_field) and not row.get(_target):
            try: row[_target]=json.loads(row.get(_json_field))
            except Exception: row[_target]=[]
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
    reliability=market_reliability_v74(item)/100
    bq=bet_quality_score_v75(item,use_odds=use_odds)/100
    score=low*.49+conf*.18+reliability*.10+bq*.23-width*.16-risk_pen
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
    bq=bet_quality_score_v75(item,use_odds=use_odds)
    if vol=="high":
        base=(low>=.68 and conf>=72 and bq>=68)
    else:
        base=(low>=.61 and conf>=62 and bq>=64)
    if not base:
        return False
    if use_odds:
        # If the user asks to use market prices, require a real reference quote and avoid a clear PASS.
        return bool(item.get("reference_odds")) and item.get("reference_verdict")!="PASS"
    return True



def prebet_quality_gate_v76(item,use_odds=False):
    """Puerta final antes de etiquetar APOSTAR. No aumenta probabilidades; solo exige integridad suficiente."""
    fam=str(item.get("market_family","") or "")
    low=float(item.get("prob_low",item.get("prob",.5)))
    conf=float(item.get("confidence_score",confidence_score(item)))
    rel=float(item.get("market_reliability",market_reliability_v74(item)))
    bq=float(item.get("bet_quality_score",bet_quality_score_v75(item,use_odds)))
    data=float(item.get("data_quality",item.get("quality",65)))
    confirmed=bool(item.get("both_lineups_confirmed",item.get("confirmed",False)))
    width=max(0,float(item.get("prob_high",item.get("prob",.5)))-float(item.get("prob_low",item.get("prob",.5))))
    sc_cov=float(item.get("statcast_coverage",0) or 0)
    reasons=[]

    # Reglas base: un verde exige una predicción razonablemente estable y datos sólidos.
    if not confirmed: reasons.append("lineups no confirmados")
    if data < 78: reasons.append(f"calidad de datos {data:.0f}/100")
    if width > .18: reasons.append("intervalo de incertidumbre demasiado amplio")
    if rel < 68: reasons.append(f"confiabilidad del mercado {rel:.0f}/100")
    if bq < 66: reasons.append(f"Bet Quality {bq:.0f}/100")

    # Props dependientes de contacto: sin Statcast suficiente pueden mostrarse, pero no recibir verde estricto.
    if fam in {"hits","total_bases","home_run"} and sc_cov < .45:
        reasons.append(f"cobertura Statcast baja ({sc_cov*100:.0f}%)")
    if fam=="home_run" and (low < .22 or conf < 70 or rel < 58):
        reasons.append("HR exige señal especialmente fuerte por su alta varianza")
    if fam=="pitcher_k" and conf < 66:
        reasons.append("Pitcher K requiere confianza >=66")
    if fam in {"fg_ml","f5_total","fg_total"} and low < .60:
        reasons.append("probabilidad conservadora de mercado de juego <60%")

    if use_odds:
        if not item.get("reference_odds"):
            reasons.append("sin momio de referencia compatible")
        elif item.get("reference_verdict")=="PASS":
            reasons.append("precio de mercado sin valor suficiente")

    status="APOSTAR" if not reasons else "REVISAR"
    return {"pass":not reasons,"status":status,"reasons":reasons}

def refresh_pick_v762(item,use_odds=False,manual_odds=None):
    """Recalculate all derived metrics after a manual line/side/odds edit."""
    y=dict(item)
    y["confidence_score"]=confidence_score(y)
    y["market_reliability"]=market_reliability_v74(y)
    risk,ricon=risk_profile_v72(y); y["risk_label"]=risk; y["risk_icon"]=ricon
    if manual_odds is not None:
        y["draftea_odds"]=float(manual_odds)
        pm=v7_price_metrics(y,float(manual_odds))
        y["manual_verdict"]=pm["verdict"]
        y["model_target_odds"]=pm["target"]
        y["manual_ev_cons"]=pm["ev_cons"]
    else:
        y["model_target_odds"]=1.05/max(float(y.get("prob_low",y.get("prob",.5))),.01)
    y["bet_quality_score"]=bet_quality_score_v75(y,use_odds=use_odds)
    y["express_safety_score"]=express_safety_score_v721(y,use_odds=use_odds)
    y["prebet_gate_v76"]=prebet_quality_gate_v76(y,use_odds=use_odds)
    return y

def rebuild_express_v762():
    """Re-rank/reclassify current Express pool after manual edits without refetching the whole slate."""
    pool=[refresh_pick_v762(x,st.session_state.get("v721_use_odds",False),x.get("draftea_odds")) for x in st.session_state.get("v762_express_prepool",[])]
    use_odds=st.session_state.get("v721_use_odds",False)
    target_n=int(st.session_state.get("v762_target_n",10))
    max_per_game=int(st.session_state.get("v762_max_per_game",1))
    diversify=bool(st.session_state.get("v762_diversify",True))
    allowed_groups=st.session_state.get("v722_allowed_groups",[])
    show_risky=bool(st.session_state.get("v724_show_risky",True))
    qualified=[y for y in pool if express_qualifies_v721(y,use_odds=use_odds) and y.get("prebet_gate_v76",{}).get("pass",False)]
    qualified=sorted(qualified,key=lambda z:z.get("express_safety_score",-9),reverse=True)
    chosen=diversify_express_v721(qualified,target_n,max_per_game=max_per_game,automatic=diversify,allowed_groups=allowed_groups)
    chosen_ids={(z.get("game_pk"),z.get("label")) for z in chosen}
    near=[z for z in pool if (z.get("game_pk"),z.get("label")) not in chosen_ids]
    near=sorted(near,key=lambda z:z.get("express_safety_score",-9),reverse=True)
    fallback=[]
    if show_risky and len(chosen)<target_n:
        counts={}
        for z in chosen: counts[z.get("game")]=counts.get(z.get("game"),0)+1
        for z in near:
            if len(fallback)>=target_n-len(chosen): break
            if counts.get(z.get("game"),0)>=max_per_game: continue
            fallback.append(z); counts[z.get("game")]=counts.get(z.get("game"),0)+1
    # Rebuild derived winner view too, so an edited ML line/side never leaves stale cards elsewhere.
    if "Full Game ML" in allowed_groups:
        _bw={}
        for z in pool:
            if z.get("market_family")!="fg_ml": continue
            gm=z.get("game")
            if gm not in _bw or z.get("prob",0)>_bw[gm].get("prob",0): _bw[gm]=z
        st.session_state["v724_best_winners"]=sorted(_bw.values(),key=lambda z:(z.get("prob_low",0),z.get("prob",0)),reverse=True)
    st.session_state["v762_express_prepool"]=pool
    st.session_state["v7_express_results"]=chosen
    st.session_state["v724_express_fallback"]=fallback
    st.session_state["v723_express_near"]=near[:max(12,target_n*2)]
    est=st.session_state.get("v723_express_stats",{})
    est.update({"prepool":len(pool),"qualified":len(qualified),"greens":len(chosen),"shown":len(chosen)+len(fallback),"fallback":len(fallback)})
    st.session_state["v723_express_stats"]=est

def build_paper_record_v762(item,odds,stake_mxn,selected_date,games,source="MANUAL",group_id=None):
    """Create one settlement-compatible Paper Bet from Express, Parlay or odds evaluation."""
    pgame=next((g for g in games if int(g.get("game_pk",0))==int(item.get("game_pk",0))),None)
    plineups=get_lineups(item.get("game_pk")) if item.get("game_pk") else {"away":[],"home":[]}
    away_ok=len(plineups.get("away",[]))>=9; home_ok=len(plineups.get("home",[]))>=9; both_ok=away_ok and home_ok
    start_dt=game_start_cdmx(pgame) if pgame else None
    htg=((start_dt-now_cdmx()).total_seconds()/3600) if start_dt else None
    freeze_level="GREEN" if both_ok and (htg is None or htg>0) else "YELLOW"
    stamp=now_cdmx()
    pid=hashlib.sha1(f"{item.get('game_pk')}|{item.get('label')}|{source}|{stamp.isoformat()}".encode()).hexdigest()[:12]
    return {
        "paper_id":pid,"timestamp":stamp.strftime("%Y-%m-%d %H:%M:%S CDMX"),"freeze_time_iso":stamp.isoformat(timespec="seconds"),
        "hours_to_game_at_freeze":round(float(htg),2) if htg is not None else None,"model_version":"V7.6.4","date":selected_date.isoformat(),
        "game_pk":int(item.get("game_pk",0) or 0),"game":item.get("game",pgame.get("label") if pgame else ""),
        "game_time_cdmx":format_game_time_cdmx(pgame.get("game_time_local")) if pgame else "",
        "away_abbr":pgame.get("away_abbr","") if pgame else "","home_abbr":pgame.get("home_abbr","") if pgame else "",
        "market":item.get("label",""),"category":item.get("category",""),"odds":round(float(odds),3),
        "stake":round(float(stake_mxn/50.0),4),"stake_mxn":round(float(stake_mxn),2),"unit_value_mxn":50.0,
        "prob_central":round(float(item.get("prob",.5)),5),"prob_low":round(float(item.get("prob_low",item.get("prob",.5))),5),
        "prob_high":round(float(item.get("prob_high",item.get("prob",.5))),5),"confidence":int(item.get("confidence_score",confidence_score(item))),
        "agreement":round(float(item.get("agreement",0)),5),"confirmed":bool(item.get("confirmed",False)),
        "away_lineup_confirmed":away_ok,"home_lineup_confirmed":home_ok,"both_lineups_confirmed":both_ok,
        "away_lineup_count":len(plineups.get("away",[])),"home_lineup_count":len(plineups.get("home",[])),
        "data_quality":int(item.get("quality",item.get("data_quality",0)) or 0),"readiness":freeze_level,"readiness_level":freeze_level,
        "freeze_type":"FINAL" if freeze_level=="GREEN" else "PRELIMINARY","status":"FROZEN","result":"PENDING","settlement_note":"",
        "paper_source":source,"paper_group_id":group_id or "","manual_line_edited":bool(item.get("manual_line_edited",False)),
        "line":item.get("line"),"side":item.get("side"),"market_family":item.get("market_family",""),"subject":item.get("subject",""),
        "bet_quality_score":int(item.get("bet_quality_score",bet_quality_score_v75(item))),
        "market_reliability":int(item.get("market_reliability",market_reliability_v74(item)))
    }

def save_paper_record_v762(rec):
    st.session_state.setdefault("v653_paper_bets",[])
    st.session_state["v653_paper_bets"].append(rec)
    return persistent_upsert_paper_bet(rec)


def build_parlay_paper_record_v764(legs,stake_mxn,selected_date,games,parlay_index=1):
    """Store a complete parlay as ONE Paper Bet while preserving every leg for settlement."""
    stamp=now_cdmx()
    gid="PAR-"+hashlib.sha1(f"{selected_date}|{parlay_index}|{stamp.isoformat()}".encode()).hexdigest()[:10]
    leg_records=[]
    combined=1.0; joint=1.0
    all_final=True
    for x in legs:
        pod=float(x.get("parlay_odds") or x.get("draftea_odds") or x.get("reference_odds") or x.get("model_target_odds") or 1.80)
        lr=build_paper_record_v762(x,pod,stake_mxn,selected_date,games,source="PARLAY_LEG",group_id=gid)
        # Legs live only inside the parent ticket; the stake is NOT counted per leg.
        lr["stake_mxn"]=0.0; lr["stake"]=0.0
        lr["paper_parent_id"]=gid
        leg_records.append(lr)
        combined*=pod
        joint*=float(x.get("prob_low",x.get("prob",0)) or 0)
        all_final=all_final and bool(lr.get("both_lineups_confirmed"))
    confs=[int(x.get("confidence",0) or 0) for x in leg_records]
    qualities=[int(x.get("data_quality",0) or 0) for x in leg_records]
    bqs=[int(x.get("bet_quality_score",0) or 0) for x in leg_records]
    return {
        "paper_id":gid,"record_type":"PARLAY","paper_source":"PARLAY","paper_group_id":gid,
        "timestamp":stamp.strftime("%Y-%m-%d %H:%M:%S CDMX"),"freeze_time_iso":stamp.isoformat(timespec="seconds"),
        "model_version":"V7.6.4","date":selected_date.isoformat(),"game_pk":0,
        "game":f"Parlay {parlay_index} · {len(leg_records)} selecciones",
        "game_time_cdmx":"Varios juegos","away_abbr":"","home_abbr":"",
        "market":f"PARLAY {len(leg_records)} LEGS","category":"Parlay","market_family":"parlay",
        "odds":round(combined,4),"stake":round(float(stake_mxn/50.0),4),"stake_mxn":round(float(stake_mxn),2),"unit_value_mxn":50.0,
        "prob_central":round(joint,6),"prob_low":round(joint,6),"prob_high":round(joint,6),
        "confidence":min(confs) if confs else 0,"data_quality":min(qualities) if qualities else 0,
        "bet_quality_score":min(bqs) if bqs else 0,"market_reliability":min([int(x.get("market_reliability",0) or 0) for x in leg_records] or [0]),
        "confirmed":all_final,"both_lineups_confirmed":all_final,"freeze_type":"FINAL" if all_final else "PRELIMINARY",
        "readiness":"GREEN" if all_final else "YELLOW","readiness_level":"GREEN" if all_final else "YELLOW",
        "status":"FROZEN","result":"PENDING","settlement_note":"","legs":leg_records,
        "leg_count":len(leg_records),"manual_line_edited":any(bool(x.get("manual_line_edited")) for x in leg_records)
    }

def settle_parlay_record_v764(record):
    """Settle the parent parlay from its embedded legs. A lost leg loses the ticket; pushes reduce leg count."""
    legs=record.get("legs") or []
    if not isinstance(legs,list) or not legs:
        return "UNSUPPORTED","Parlay sin piernas guardadas",[]
    leg_states=[]; any_pending=False; any_lost=False; won_count=push_count=0
    for leg in legs:
        gr=get_game_result_v65(leg.get("game_pk"))
        if not gr.get("final"):
            verdict,note="PENDING","Partido aún no finaliza"
            any_pending=True
        else:
            verdict,note=settle_market_v65(leg,gr)
            if verdict=="LOST": any_lost=True
            elif verdict=="WON": won_count+=1
            elif verdict=="PUSH": push_count+=1
            elif verdict in ("PENDING","UNSUPPORTED"): any_pending=True
        leg_states.append({"game":leg.get("game"),"market":leg.get("market"),"odds":leg.get("odds"),"result":verdict,"note":note})
    if any_lost:
        overall="LOST"
    elif any_pending:
        overall="PENDING"
    elif won_count==0 and push_count==len(legs):
        overall="PUSH"
    else:
        overall="WON"
    note=f"{won_count} ganadas · {sum(x['result']=='LOST' for x in leg_states)} perdidas · {push_count} push · {sum(x['result']=='PENDING' for x in leg_states)} pendientes"
    return overall,note,leg_states

def market_group_v722(item):
    """V7.5: familias concretas para que Express analice exactamente lo elegido."""
    fam=str(item.get("market_family","") or "")
    if fam=="f5_total": return "F5 Carreras"
    if fam=="fg_ml": return "Full Game ML"
    if fam=="fg_total": return "Full Game Carreras"
    if fam=="pitcher_k": return "Pitcher Ks"
    if fam in {"hits","total_bases","hrr","home_run"}: return "Batter props"
    # F5 ML puede existir en el análisis individual, pero no forma parte de Express V7.2.5.
    if fam=="f5_ml": return "F5 ML (no Express)"
    cat=str(item.get("category","") or "")
    if "Pitcher" in cat: return "Pitcher Ks"
    if "Full Game" in cat and "ML" in str(item.get("label","")): return "Full Game ML"
    if "Full Game" in cat: return "Full Game Carreras"
    if "F5" in cat: return "F5 Carreras"
    return "Batter props"

def family_shortlist_v722(items, per_group=8):
    """V7.2.5: preserva candidatos de TODAS las familias sin borrarlos por umbrales tempranos.
    La clasificación APOSTAR/PASS se hace después. Así Express nunca aparenta no haber analizado.
    """
    enriched=[]
    for item in items:
        x=dict(item)
        x["confidence_score"]=confidence_score(x)
        x["express_group"]=market_group_v722(x)
        enriched.append(x)
    out=[]
    for group in ["F5 Carreras","Full Game ML","Full Game Carreras","Pitcher Ks","Batter props"]:
        g=[x for x in enriched if x["express_group"]==group]
        g=sorted(g,key=lambda x:(x.get("prob_low",0),x.get("confidence_score",0),x.get("prob",0)),reverse=True)
        # Mantiene un bloque amplio de cada familia para el ranking global y el fallback.
        out.extend(g[:max(per_group,12)])
    return out

def diversify_express_v721(pool,target_n,max_per_game=1,automatic=True,allowed_groups=None):
    """V7.2.3: una sola familia no puede monopolizar Express."""
    allowed_groups=set(allowed_groups or ["F5 Carreras","Full Game ML","Full Game Carreras","Pitcher Ks","Batter props"])
    pool=[x for x in pool if market_group_v722(x) in allowed_groups]
    if not automatic: return pool[:target_n]
    selected=[]; game_counts={}; player_counts={}; group_counts={}
    caps={
        "Pitcher Ks": min(2,max(1,math.ceil(target_n*.20))),
        "Batter props": max(1,math.ceil(target_n*.30)),
        "F5 Carreras": max(1,math.ceil(target_n*.40)),
        "Full Game ML": max(1,math.ceil(target_n*.30)),
        "Full Game Carreras": max(1,math.ceil(target_n*.30)),
    }
    grouped={}
    for x in pool: grouped.setdefault(market_group_v722(x),[]).append(x)
    for g in grouped: grouped[g]=sorted(grouped[g],key=lambda z:z.get("express_safety_score",-9),reverse=True)
    order=[g for g in ["F5 Carreras","Full Game ML","Full Game Carreras","Batter props","Pitcher Ks"] if g in allowed_groups]
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
                if group in {"Pitcher Ks","Batter props"} and subj and player_counts.get(subj,0)>=1: continue
                selected.append(x); progress=True
                game_counts[game]=game_counts.get(game,0)+1; group_counts[group]=group_counts.get(group,0)+1
                if group in {"Pitcher Ks","Batter props"} and subj: player_counts[subj]=1
                break
    return selected

# ================= V7 EXPRESS ENGINE =================
def analyze_game_express_v7(g,selected_date,allowed_groups=None):
    d=selected_date.isoformat() if hasattr(selected_date,"isoformat") else str(selected_date)
    season=selected_date.year if hasattr(selected_date,"year") else int(d[:4])
    away_form=get_team_form(g["away_id"],d);home_form=get_team_form(g["home_id"],d)
    allowed=set(allowed_groups or ["F5 Carreras","Full Game ML","Full Game Carreras","Pitcher Ks","Batter props"])
    away_pitch=get_pitcher_stats(g["away_pitcher_id"],season) if g.get("away_pitcher_id") else None
    home_pitch=get_pitcher_stats(g["home_pitcher_id"],season) if g.get("home_pitcher_id") else None
    away_pitch=attach_pitcher_statcast(away_pitch,g.get("away_pitcher_name"),season)
    home_pitch=attach_pitcher_statcast(home_pitch,g.get("home_pitcher_name"),season)
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
    if "F5 Carreras" in allowed:
      for line in [3.5,4.5,5.5,6.5]:
          for side,word in [("over","Over"),("under","Under")]:
            p0=_sample_prob(totalvals,line,side);lo,hi=_bands_from_sample_prob(p0,both,"medium")
            items.append({"category":"F5","label":f"F5 {word} {line:g}","prob":p0,"prob_low":lo,"prob_high":hi,
                          "agreement":.90 if both else .75,"quality":q,"confirmed":both,"volatility":"medium",
                          "market_family":"f5_total","side":side,"line":line,"sample_values":totalvals,"subject":f"{g['away_abbr']} @ {g['home_abbr']}"})
    # V7.2.5: Express prioriza F5 carreras; F5 ML se mantiene solo en análisis individual.

    # Lightweight Full Game totals. Bullpen/staff adds uncertainty; these must clear the same conservative filters.
    away_staff=get_team_pitching_profile(g["away_id"],season,d)
    home_staff=get_team_pitching_profile(g["home_id"],season,d)
    away_bp_work=get_bullpen_workload(g["away_id"],d); home_bp_work=get_bullpen_workload(g["home_id"],d)
    if away_staff is not None: away_staff={**away_staff,"workload_fatigue":away_bp_work.get("fatigue_score",.35)}
    if home_staff is not None: home_staff={**home_staff,"workload_fatigue":home_bp_work.get("fatigue_score",.35)}
    away_fg,home_fg,fgd=project_full_game_ensemble_v73(af,hf,away_form,home_form,away_staff,home_staff,
        away_pitch,home_pitch,away_lineup,home_lineup,both,pf,weather)
    fgq=max(38,q-5)
    staff_spread=abs(float(fgd.get("away_staff_factor",1.0))-1)+abs(float(fgd.get("home_staff_factor",1.0))-1)
    fatigue_spread=abs(float((away_staff or {}).get("workload_fatigue",.35))-float((home_staff or {}).get("workload_fatigue",.35)))
    fgsim=simulate_run_environment(away_fg,home_fg,fgq,both,stable_seed(g["game_pk"],d,"EXPRESS-FG-V75"),n=12000,full_game=True,
        model_disagreement=ad["model_disagreement"]+hd["model_disagreement"]+.35*staff_spread+.12*fatigue_spread)
    fgvals=fgsim["away"]+fgsim["home"]
    if "Full Game Carreras" in allowed:
      for line in [7.5,8.5,9.5,10.5]:
        for side,word in [("over","Over"),("under","Under")]:
            p0=_sample_prob(fgvals,line,side); lo,hi=_bands_from_sample_prob(p0,False,"medium")
            items.append({"category":"Full Game","label":f"Full Game {word} {line:g}","prob":p0,"prob_low":lo,"prob_high":hi,
                          "agreement":.82 if both else .74,"quality":fgq,"confirmed":both,"volatility":"medium",
                          "market_family":"fg_total","side":side,"line":line,"sample_values":fgvals,"subject":f"{g['away_abbr']} @ {g['home_abbr']}"})

    # Full Game Moneyline V7.5: simulación + fuerza + bullpen + Statcast contextual.
    if "Full Game ML" in allowed:
      for side,abbr in [("away",g["away_abbr"]),("home",g["home_abbr"])]:
        p0,scen,mld=full_game_ml_probability_v73(fgsim,side,away_form,home_form,away_staff,home_staff,fgd)
        lo0=min(scen+[p0]) if scen else p0; hi0=max(scen+[p0]) if scen else p0
        width=.035 if both else .065
        lo=clamp(lo0-width,.01,.99); hi=clamp(hi0+width,.01,.99)
        agr=clamp(1-(hi0-lo0),.55,.98)
        reason=(f"V7.5 ML · marcador medio {g['away_abbr']} {away_fg:.2f} - {g['home_abbr']} {home_fg:.2f} · "
                f"fuerza reg. {g['away_abbr']} {mld['away_strength']:.3f} / {g['home_abbr']} {mld['home_strength']:.3f} · "
                f"bullpen carga {g['away_abbr']} {(away_staff or {}).get('workload_fatigue',.35)*100:.0f}% / {g['home_abbr']} {(home_staff or {}).get('workload_fatigue',.35)*100:.0f}%.")
        items.append({"category":"Full Game","label":f"{abbr} ML Full Game","prob":p0,"prob_low":lo,"prob_high":hi,
                      "agreement":agr,"quality":fgq,"confirmed":both,"volatility":"medium",
                      "market_family":"fg_ml","side":side,"line":0.0,"sample_values":None,"subject":abbr,
                      "reason":reason,"ml_details":{"away_proj":away_fg,"home_proj":home_fg,**mld}})

    if "Pitcher Ks" in allowed or "Batter props" in allowed:
        pr=build_prop_candidates_v7(away_pitch,home_pitch,g['away_pitcher_name'],g['home_pitcher_name'],away_lineup,home_lineup,both,pf,weather)
        if "Pitcher Ks" not in allowed: pr=[z for z in pr if z.get("market_family")!="pitcher_k"]
        if "Batter props" not in allowed: pr=[z for z in pr if z.get("market_family") not in {"hits","total_bases","hrr","home_run"}]
        items.extend(pr)
    sc_count=sum(1 for z in (away_lineup+home_lineup) if (z.get("statcast") or {}).get("available"))
    sc_den=max(1,min(18,len(away_lineup)+len(home_lineup)))
    sc_cov=sc_count/sc_den
    items=[apply_market_calibration_v75(z) for z in items]
    ranked=family_shortlist_v722(items,per_group=8)
    for x in ranked:
        x["game"]=g["label"];x["game_pk"]=g["game_pk"];x["game_time_cdmx"]=format_game_time_cdmx(g.get("game_time_local"));x["data_quality"]=q;x["both_lineups_confirmed"]=both
        x["statcast_count"]=sc_count;x["statcast_coverage"]=sc_cov
        # Precio mínimo como referencia de modelo; no se presenta como cuota de sportsbook.
        x["model_target_odds"]=1.05/max(x.get("prob_low",x["prob"]),.01)
        x["market_reliability"]=market_reliability_v74(x)
        x["bet_quality_score"]=bet_quality_score_v75(x,False)
    return ranked,{"quality":q,"both":both,"statcast":sc_count>0,"statcast_count":sc_count,"statcast_coverage":sc_cov}

# ================= APP UI =================
st.set_page_config(page_title="MLB Betting Hub V7.6.4", page_icon="⚾", layout="wide")
st.title("⚾ MLB Betting Hub — V7.6.4 Alpha")
st.caption("V7.6.4: Paper Parlays completos + Multi-Parlay independiente + edición/recalculo total + Pre-Bet Hardening + Statcast/Savant + calibración.")
st.info("🎟️ **V7.6.4 ALPHA — PAPER PARLAYS COMPLETOS** — Mantiene Statcast/Savant de V7.5 y añade puertas de calidad más estrictas antes de marcar un pick como APOSTAR. Un mercado puede tener buena probabilidad y aun así quedar en REVISAR si faltan lineup, calidad de datos, cobertura Statcast crítica o estabilidad suficiente.")

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
    away_pitch=attach_pitcher_statcast(away_pitch,game.get("away_pitcher_name"),selected_date.year)
    home_pitch=attach_pitcher_statcast(home_pitch,game.get("home_pitcher_name"),selected_date.year)
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
_sc_n=sum(1 for z in (away_lineup+home_lineup) if (z.get("statcast") or {}).get("available"))
if _sc_n: quality_notes.append(f"✅ Baseball Savant/Statcast disponible para {_sc_n} bateadores del lineup")
else: quality_notes.append("ℹ️ Savant no disponible en esta consulta; usando fallback MLB StatsAPI")
quality=max(30,min(100,quality))

park_factor=(park or {}).get("factor",1.0)

away_f5,away_f5_debug=project_f5_ensemble(away_form,home_pitch,away_lineup,away_confirmed,park_factor,weather)
home_f5,home_f5_debug=project_f5_ensemble(home_form,away_pitch,home_lineup,home_confirmed,park_factor,weather)
f5_total=away_f5+home_f5

away_fg,home_fg,fg_debug=project_full_game_ensemble_v73(
    away_f5,home_f5,away_form,home_form,away_staff,home_staff,
    away_pitch,home_pitch,away_lineup,home_lineup,both_confirmed,park_factor,weather
)
fg_total=away_fg+home_fg

# Monte Carlo predictive distributions.
f5_disagreement=away_f5_debug["model_disagreement"]+home_f5_debug["model_disagreement"]
f5_sim=simulate_run_environment(
    away_f5,home_f5,quality,both_confirmed,
    stable_seed(game["game_pk"],selected_date.isoformat(),"F5"),
    n=24000,full_game=False,model_disagreement=f5_disagreement
)
fg_staff_spread=abs(float(fg_debug.get("away_staff_factor",1.0))-1)+abs(float(fg_debug.get("home_staff_factor",1.0))-1)
fg_fatigue_spread=abs(float((away_staff or {}).get("workload_fatigue",.35))-float((home_staff or {}).get("workload_fatigue",.35)))
fg_sim=simulate_run_environment(
    away_fg,home_fg,max(38,quality-6),both_confirmed,
    stable_seed(game["game_pk"],selected_date.isoformat(),"FG-V75"),
    n=32000,full_game=True,model_disagreement=f5_disagreement+.35*fg_staff_spread+.12*fg_fatigue_spread
)

props=build_prop_candidates_v7(
    away_pitch,home_pitch,game["away_pitcher_name"],game["home_pitcher_name"],
    away_lineup,home_lineup,both_confirmed,park_factor,weather
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
    st.caption("V7.5 usa submodelos separados para ML, carreras, K, Hits, Total Bases, HRR y HR. Integra splits MLB, contexto de lineup, pitcher, bullpen, parque y clima. Statcast/Savant se consulta directamente de Baseball Savant y se usa cuando responde. Si faltan campos o la fuente falla, el motor cae a StatsAPI sin fabricar valores.")

    current_context_snapshot=make_context_snapshot(
        game,away_pitch,home_pitch,away_lineup,home_lineup,weather,
        away_bp_work,home_bp_work,f5_total,fg_total
    )
    changes=context_changes(st.session_state.get("v653_previous_context"),current_context_snapshot)
    if changes:
        with st.expander("🆕 Qué cambió desde tu última actualización",expanded=True):
            for ch in changes:
                st.write(f"• {ch}")

# Acciones principales fuera del expander de contexto.
st.caption("Acciones del partido seleccionado")
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
    center,scenario,mld=full_game_ml_probability_v73(fg_sim,side,away_form,home_form,away_staff,home_staff,fg_debug)
    p,lo,hi,agreement=conservative_probability(center,scenario,max(38,quality-6),both_confirmed,"medium")
    automatic.append({
        "category":"Full Game","label":f"{abbr} ML Full Game",
        "prob":p,"prob_low":lo,"prob_high":hi,"agreement":agreement,
        "quality":max(38,quality-6),"confirmed":both_confirmed,"volatility":"medium",
        "market_family":"fg_ml","side":side,"line":0.0,"subject":abbr,
        "reason":f"V7.5 Game Engine · proyección {game['away_abbr']} {away_fg:.2f} - {game['home_abbr']} {home_fg:.2f} · fuerza reg. {mld['away_strength']:.3f}/{mld['home_strength']:.3f} · bullpen y localía incluidos."
    })

automatic.extend(props)
automatic=[apply_market_calibration_v75(z) for z in automatic]
for _z in automatic:
    _z["market_reliability"]=market_reliability_v74(_z)
    _z["bet_quality_score"]=bet_quality_score_v75(_z,False)
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
                f"Acuerdo **{item.get('agreement',0)*100:.0f}%** · Bet Quality **{item.get('bet_quality_score',bet_quality_score_v75(item))}/100** · {predictor_state}"
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
    allowed_groups=st.multiselect(
        "Mercados a analizar",
        ["F5 Carreras","Full Game ML","Full Game Carreras","Pitcher Ks","Batter props"],
        default=["F5 Carreras","Full Game ML","Full Game Carreras"],
        help="F5 analiza solo carreras Over/Under. En Full Game puedes elegir por separado ganador (ML) y carreras Over/Under. Pitcher Ks y Batter props son opcionales."
    )
    max_per_game=int(st.number_input("Máximo de selecciones por partido",min_value=1,max_value=3,value=1,step=1,help="Permite hasta 1, 2 o 3 selecciones del mismo juego dentro del Top."))
    show_risky=st.toggle("Si no hay suficientes verdes, mostrar las mejores alternativas con riesgo",value=True,help="No las marca como seguras: simplemente muestra las de mayor probabilidad disponible con su nivel de riesgo y confianza.")
    st.caption("🎯 Primero se rankea cada familia por separado y después se arma el Top. Si faltan picks verdes, puedes ver el mejor Top disponible aunque incluya riesgo.")

    nowx=now_cdmx()
    future_games=[g for g in games if game_is_pregame(g,nowx)]
    live_games=[g for g in games if str(g.get("abstract_state","")).lower()=="live" or "progress" in str(g.get("detailed_state","")).lower()]
    final_games=[g for g in games if str(g.get("abstract_state","")).lower()=="final"]
    started_count=len(games)-len(future_games)
    j1,j2,j3,j4=st.columns(4)
    j1.metric("Jornada",len(games));j2.metric("Sin iniciar",len(future_games));j3.metric("En juego",len(live_games));j4.metric("Finalizados",len(final_games))
    st.caption(f"🕒 {nowx.strftime('%I:%M:%S %p')} CDMX · Express vuelve a consultar estado y lineups en cada búsqueda; Live/Final se excluyen.")

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

        allp=[]; express_errors=[]
        prog=st.progress(0,text="2/2 Análisis profundo solo de los mercados seleccionados...")
        for i,g in enumerate(eligible):
            try:
                picks,meta=analyze_game_express_v7(g,selected_date,allowed_groups=allowed_groups)
                allp.extend(picks)
            except Exception as ex:
                express_errors.append(f"{g.get('label')}: {type(ex).__name__}: {ex}")
            prog.progress((i+1)/max(1,len(eligible)),text=f"Analizados {i+1}/{len(eligible)}")
        prog.empty()

        enriched=[]
        for x in allp:
            y=dict(x); y["confidence_score"]=confidence_score(y)
            risk,ricon=risk_profile_v72(y); y["risk_label"]=risk; y["risk_icon"]=ricon
            y["bet_quality_score"]=bet_quality_score_v75(y,use_odds=False)
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
            y["bet_quality_score"]=bet_quality_score_v75(y,use_odds=use_odds)
            y["express_safety_score"]=express_safety_score_v721(y,use_odds=use_odds)
        for y in prepool:
            y["prebet_gate_v76"]=prebet_quality_gate_v76(y,use_odds=use_odds)
        qualified=[y for y in prepool if express_qualifies_v721(y,use_odds=use_odds) and y.get("prebet_gate_v76",{}).get("pass",False)]
        qualified=sorted(qualified,key=lambda z:z.get("express_safety_score",-9),reverse=True)
        chosen=diversify_express_v721(qualified,target_n,max_per_game=max_per_game,automatic=diversify,allowed_groups=allowed_groups)
        chosen_ids={(z.get("game_pk"),z.get("label")) for z in chosen}
        near=[z for z in prepool if (z.get("game_pk"),z.get("label")) not in chosen_ids]
        near=sorted(near,key=lambda z:z.get("express_safety_score",-9),reverse=True)

        # V7.5 fallback: si el usuario pidió N y hay menos verdes, completa SOLO la visualización
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
        winner_pool=[z for z in prepool if z.get("market_family")=="fg_ml"]
        best_winners=[]
        by_game={}
        for z in winner_pool:
            fam=z.get("market_family")
            # Solo se calcula esta vista si el usuario activó Full Game ML.
            if "Full Game ML" not in allowed_groups: continue
            key=(z.get("game"),fam)
            if key not in by_game or z.get("prob",0)>by_game[key].get("prob",0): by_game[key]=z
        for (gm,fam),z in by_game.items():
            best_winners.append(z)
        best_winners=sorted(best_winners,key=lambda z:(z.get("prob_low",0),z.get("prob",0)),reverse=True)
        st.session_state["v724_best_winners"]=best_winners
        st.session_state["v762_express_prepool"]=prepool
        st.session_state["v762_target_n"]=target_n
        st.session_state["v762_max_per_game"]=max_per_game
        st.session_state["v762_diversify"]=diversify
        st.session_state["v7_express_results"]=chosen
        st.session_state["v724_express_fallback"]=fallback
        st.session_state["v723_express_near"]=near[:max(12,target_n*2)]
        st.session_state["v723_express_stats"]={"markets":len(allp),"prepool":len(prepool),"qualified":len(qualified),"shown":len(shown_all),"greens":len(chosen),"fallback":len(fallback)}
        st.session_state["v721_use_odds"]=use_odds
        st.session_state["v72_express_lineup_mode"]=lineup_mode
        st.session_state["v722_allowed_groups"]=allowed_groups
        st.session_state["v724_show_risky"]=show_risky
        st.session_state["v75_express_errors"]=express_errors

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
    _errs=st.session_state.get("v75_express_errors",[])
    if _errs:
        st.warning(f"⚠️ {len(_errs)} partido(s) tuvieron error de análisis. Ya no se ocultan silenciosamente.")
        with st.expander("Ver errores de análisis"):
            for _e in _errs: st.code(_e)
    best_winners=st.session_state.get("v724_best_winners",[])
    if best_winners and "Full Game ML" in st.session_state.get("v722_allowed_groups",[]):
        with st.expander("🏆 Ganador con mayor probabilidad por partido — aunque no llegue a verde", expanded=False):
            st.caption("Aquí V7 compara los dos equipos y muestra el lado con mayor probabilidad del modelo. Si no alcanza nivel verde, se marca como riesgo y NO como apuesta segura.")
            for z in best_winners[:15]:
                rr,ri=risk_profile_v72(z)
                st.markdown(f"**{z.get('game','')} → {z.get('label','')}** · Central {z.get('prob',0)*100:.1f}% · Conservadora {z.get('prob_low',0)*100:.1f}% · Conf. {z.get('confidence_score',0)}/100 · Confiab. mercado {z.get('market_reliability',market_reliability_v74(z))}/100 · Calidad apuesta {z.get('bet_quality_score',bet_quality_score_v75(z))}/100 · {ri} {rr}")
    if display_express:
        with st.expander("⭐ Mejor apuesta de cada partido analizado",expanded=False):
            bygm={}
            for _z in (st.session_state.get("v7_express_results",[])+st.session_state.get("v724_express_fallback",[])+st.session_state.get("v723_express_near",[])):
                _gm=_z.get("game")
                _score=_z.get("bet_quality_score",bet_quality_score_v75(_z,st.session_state.get("v721_use_odds",False)))
                if _gm and (_gm not in bygm or _score>bygm[_gm][0]): bygm[_gm]=(_score,_z)
            for _gm,(_score,_z) in sorted(bygm.items(),key=lambda kv:kv[1][0],reverse=True):
                st.markdown(f"**{_gm} → {_z.get('label')}** · Bet Quality {_score}/100 · Central {_z.get('prob',0)*100:.1f}% · Conservadora {_z.get('prob_low',0)*100:.1f}%")
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
                m1,m2,m3,m4,m5,m6=st.columns(6)
                m1.metric("Prob. central",f"{x.get('prob',0)*100:.1f}%")
                m2.metric("Conservadora",f"{x.get('prob_low',0)*100:.1f}%")
                m3.metric("Confianza",f"{x.get('confidence_score',0)}/100")
                m4.metric("Confiab. mercado",f"{x.get('market_reliability',market_reliability_v74(x))}/100")
                m5.metric("Bet Quality",f"{x.get('bet_quality_score',bet_quality_score_v75(x))}/100")
                m6.metric("Riesgo",f"{ricon} {risk}")
                if x.get("line_repriced"):
                    st.caption(f"🔄 Línea de mercado detectada y recalculada: {float(x.get('original_model_line')):g} → {float(x.get('line')):g}.")
                if x.get("reference_odds"):
                    st.caption(f"🌐 Ref. {x['reference_odds']:.2f}x · mínimo modelo {x.get('reference_target_odds',x.get('model_target_odds',0)):.2f}x · EV conservador {x.get('reference_ev_cons',0)*100:+.1f}% · {x.get('reference_books',0)} casas")
                else:
                    st.caption(f"Momio mínimo orientativo ≈ {x.get('model_target_odds',0):.2f}x · esta selección fue elegida por probabilidad + confianza + riesgo; el precio no intervino en el ranking.")
                if x.get("reason"): st.caption("📌 "+x["reason"])
                _gate=x.get("prebet_gate_v76") or prebet_quality_gate_v76(x,st.session_state.get("v721_use_odds",False))
                if _gate.get("pass"):
                    st.caption(f"🛡️ Gate V7.6.4: APOSTAR · Statcast lineup {float(x.get('statcast_coverage',0))*100:.0f}%")
                else:
                    st.caption("🛡️ Gate V7.6.4: REVISAR · " + " · ".join(_gate.get("reasons",[])[:4]))
                _cal=x.get("calibration_v75") or {}
                if _cal.get("active"):
                    st.caption(f"🎯 Calibración histórica activa: N={_cal.get('n')} · ajuste {float(_cal.get('delta',0))*100:+.1f} pp (limitado y regresado).")

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
                            if st.button("🔄 Aplicar cambio y actualizar TODO Express",key=f"v721_apply_{x['game_pk']}_{i}",use_container_width=True):
                                rx["manual_line_edited"]=True
                                rx["reference_odds"]=None
                                rx["reference_ev_cons"]=None
                                rx=refresh_pick_v762(rx,use_odds=False,manual_odds=float(od))
                                old_key=(x.get("game_pk"),x.get("label"))
                                pool=list(st.session_state.get("v762_express_prepool",[]))
                                found=False
                                for kk,z in enumerate(pool):
                                    if (z.get("game_pk"),z.get("label"))==old_key:
                                        pool[kk]=rx; found=True; break
                                if not found:
                                    pool.append(rx)
                                st.session_state["v762_express_prepool"]=pool
                                rebuild_express_v762()
                                st.success("Cambio aplicado. Recalculé probabilidad, conservadora, confianza, riesgo, Bet Quality, Gate y el ranking completo de Express con la nueva línea/momio.")
                                st.rerun()

                with st.expander("🧪 Guardar esta selección en Paper Bets"):
                    _paper_default_od=float(x.get("draftea_odds") or x.get("reference_odds") or x.get("model_target_odds") or 1.80)
                    _pc1,_pc2=st.columns(2)
                    _paper_od=_pc1.number_input("Momio a congelar",min_value=1.01,max_value=100.0,value=float(round(_paper_default_od,2)),step=.01,key=f"v762_exp_paper_od_{x.get('game_pk')}_{i}")
                    _paper_stake=_pc2.number_input("Monto simulado (MXN)",min_value=5.0,max_value=10000.0,value=50.0,step=5.0,key=f"v762_exp_paper_stake_{x.get('game_pk')}_{i}")
                    if st.button("🧊 Guardar en Paper Bets",key=f"v762_exp_paper_save_{x.get('game_pk')}_{i}",use_container_width=True):
                        _rec=build_paper_record_v762(x,_paper_od,_paper_stake,selected_date,games,source="EXPRESS")
                        _ok=save_paper_record_v762(_rec)
                        if _ok: st.success("Paper Bet guardada desde Express.")
                        else: st.warning("Se guardó en sesión, pero falló la persistencia externa/local.")
                    
    else:
        if estats:
            st.warning("No encontré candidatos utilizables con esos mercados/filtros. Si 'Mercados generados' es 0, hay un problema de generación de candidatos y no una ausencia real de juegos.")
        else:
            st.info("Ejecuta Express para ver el Top disponible en este momento.")

with tabParlay:
    st.subheader("🎟️ Parlays independientes — toda la jornada")
    st.caption("Este módulo NO depende de Express. Puedes pedir 1 a 5 parlays; cada búsqueda vuelve a revisar toda la jornada, excluye juegos ya iniciados y arma cada ticket según tus mercados, número de juegos y perfil.")

    pc1,pc2,pc3,pc4=st.columns(4)
    parlay_count=int(pc1.number_input("¿Cuántos parlays quieres?",min_value=1,max_value=5,value=1,step=1,key="v763_parlay_count"))
    parlay_legs=int(pc2.number_input("Juegos por parlay",min_value=2,max_value=8,value=3,step=1,key="v763_parlay_legs"))
    parlay_profile=pc3.selectbox("Perfil del parlay",["Menor riesgo","Equilibrado","Mayor ganancia"],index=1,key="v763_parlay_profile")
    parlay_lineups=pc4.selectbox("Lineups",["Solo completos","Completos o pendientes"],index=0,key="v763_parlay_lineups")

    parlay_market_choices=st.multiselect(
        "Mercados a analizar para los parlays",
        ["F5 Carreras","Full Game ML","Full Game Carreras","Pitcher Ks","Hits","Total Bases","HRR","Home Run"],
        default=["F5 Carreras","Full Game ML","Full Game Carreras"],
        key="v763_parlay_markets",
        help="Puedes mezclar mercados. Cada parlay usa como máximo una selección por partido."
    )
    po1,po2=st.columns(2)
    parlay_avoid_repeat=po1.toggle("Evitar repetir la misma selección entre parlays",value=True,key="v763_parlay_avoid_repeat",help="Activado: una apuesta exacta no se reutiliza en otro parlay. El mismo partido sí puede aparecer con otro mercado si el modelo encuentra una opción distinta.")
    parlay_use_odds=po2.toggle("Usar momios de referencia",value=False,key="v763_parlay_use_odds",help="Si está apagado, Mayor ganancia usa el momio mínimo orientativo del modelo. Si está encendido, intenta usar cuotas de referencia y puede consumir créditos de The Odds API.")

    if parlay_profile=="Menor riesgo":
        st.info("🛡️ Menor riesgo: prioriza probabilidad conservadora, confianza, Bet Quality y Gate V7.6.4. Si no alcanza la calidad, puede entregar menos parlays o menos piernas.")
    elif parlay_profile=="Equilibrado":
        st.info("⚖️ Equilibrado: combina probabilidad/solidez con una cuota razonable. Puede usar picks amarillos fuertes para completar tickets, siempre identificados como riesgo.")
    else:
        st.warning("💰 Mayor ganancia: aumenta el peso del momio potencial, pero conserva pisos mínimos de probabilidad y calidad; no busca combinaciones puramente especulativas.")

    nowp=now_cdmx()
    parlay_future=[g for g in games if game_is_pregame(g,nowp)]
    pp1,pp2,pp3,pp4=st.columns(4)
    pp1.metric("Partidos de la jornada",len(games))
    pp2.metric("Aún no iniciados",len(parlay_future))
    pp3.metric("Parlays solicitados",parlay_count)
    pp4.metric("Juegos por parlay",parlay_legs)

    if st.button("🎟️ Buscar parlays en toda la jornada",type="primary",use_container_width=True,key="v763_build_independent_parlays"):
        engine_groups=[]
        if "F5 Carreras" in parlay_market_choices: engine_groups.append("F5 Carreras")
        if "Full Game ML" in parlay_market_choices: engine_groups.append("Full Game ML")
        if "Full Game Carreras" in parlay_market_choices: engine_groups.append("Full Game Carreras")
        if "Pitcher Ks" in parlay_market_choices: engine_groups.append("Pitcher Ks")
        batter_selected=any(m in parlay_market_choices for m in ["Hits","Total Bases","HRR","Home Run"])
        if batter_selected: engine_groups.append("Batter props")

        family_allowed=set()
        if "F5 Carreras" in parlay_market_choices: family_allowed.add("f5_total")
        if "Full Game ML" in parlay_market_choices: family_allowed.add("fg_ml")
        if "Full Game Carreras" in parlay_market_choices: family_allowed.add("fg_total")
        if "Pitcher Ks" in parlay_market_choices: family_allowed.add("pitcher_k")
        if "Hits" in parlay_market_choices: family_allowed.add("hits")
        if "Total Bases" in parlay_market_choices: family_allowed.add("total_bases")
        if "HRR" in parlay_market_choices: family_allowed.add("hrr")
        if "Home Run" in parlay_market_choices: family_allowed.add("home_run")

        eligible=[]; complete=0; pending=0
        lineprog=st.progress(0,text="1/3 Revisando horarios y lineups...")
        for i,g in enumerate(parlay_future):
            raw=get_lineups(g["game_pk"])
            both=len(raw.get("away",[]))>=9 and len(raw.get("home",[]))>=9
            complete+=int(both); pending+=int(not both)
            if parlay_lineups=="Solo completos" and not both:
                lineprog.progress((i+1)/max(1,len(parlay_future)),text=f"Lineups {i+1}/{len(parlay_future)}")
                continue
            eligible.append(g)
            lineprog.progress((i+1)/max(1,len(parlay_future)),text=f"Lineups {i+1}/{len(parlay_future)}")
        lineprog.empty()

        candidates=[]; perrors=[]
        aprog=st.progress(0,text="2/3 Analizando todos los juegos elegibles...")
        for i,g in enumerate(eligible):
            try:
                picks,_=analyze_game_express_v7(g,selected_date,allowed_groups=engine_groups)
                picks=[x for x in picks if x.get("market_family") in family_allowed]
                candidates.extend(picks)
            except Exception as ex:
                perrors.append(f"{g.get('label')}: {type(ex).__name__}: {ex}")
            aprog.progress((i+1)/max(1,len(eligible)),text=f"Analizados {i+1}/{len(eligible)}")
        aprog.empty()

        enriched=[]
        for x in candidates:
            y=dict(x)
            y["confidence_score"]=confidence_score(y)
            risk,ricon=risk_profile_v72(y); y["risk_label"]=risk; y["risk_icon"]=ricon
            y["bet_quality_score"]=bet_quality_score_v75(y,use_odds=False)
            enriched.append(y)
        enriched=sorted(enriched,key=lambda z:(z.get("prob_low",0),z.get("bet_quality_score",0)),reverse=True)
        usage={}
        if parlay_use_odds and odds_api_enabled() and enriched:
            enriched,usage=enrich_candidates_reference_odds(enriched,games)
        for y in enriched:
            y["bet_quality_score"]=bet_quality_score_v75(y,use_odds=parlay_use_odds)
            y["prebet_gate_v76"]=prebet_quality_gate_v76(y,use_odds=parlay_use_odds)
            y["parlay_odds"]=float(y.get("reference_odds") or y.get("model_target_odds") or (1.0/max(y.get("prob_low",.5),.01)))

        def _parlay_leg_score(y):
            p=float(y.get("prob_low",y.get("prob",0)))
            conf=float(y.get("confidence_score",0))/100
            bq=float(y.get("bet_quality_score",0))/100
            rel=float(y.get("market_reliability",market_reliability_v74(y)))/100
            odd=max(1.01,float(y.get("parlay_odds",1.01)))
            gate=1.0 if y.get("prebet_gate_v76",{}).get("pass",False) else 0.0
            vol={"low":1.0,"medium":.82,"high":.58}.get(str(y.get("volatility","medium")).lower(),.75)
            if parlay_profile=="Menor riesgo":
                return 5.0*p + 1.4*conf + 1.4*bq + .9*rel + .8*gate + .5*vol - .10*max(0,odd-2.2)
            if parlay_profile=="Equilibrado":
                return 3.5*p + 1.1*conf + 1.2*bq + .7*rel + .45*gate + .35*vol + .32*min(odd,4.0)
            if p < .43 or bq < .48: return -99
            return 2.25*p + .75*conf + .8*bq + .35*rel + .20*gate + .18*vol + .78*min(odd,6.0)

        for y in enriched:
            y["parlay_leg_score"]=_parlay_leg_score(y)

        def _pick_signature(y):
            return "|".join([
                str(y.get("game_pk","")),str(y.get("market_family","")),str(y.get("player_id") or y.get("player") or ""),
                str(y.get("side","")),str(y.get("line","")),str(y.get("label",""))
            ])

        base_pool=[y for y in enriched if (y.get("prebet_gate_v76",{}).get("pass",False) if parlay_profile=="Menor riesgo" else y.get("parlay_leg_score",-99)>-90)]
        used_signatures=set(); built=[]

        for pidx in range(parlay_count):
            available=[y for y in base_pool if (not parlay_avoid_repeat or _pick_signature(y) not in used_signatures)]
            best_by_game={}
            for y in available:
                gk=y.get("game_pk")
                # tiny rotation penalty encourages different market choices on later tickets when scores are close
                diversity_penalty=.025*pidx if _pick_signature(y) in used_signatures else 0.0
                score=float(y.get("parlay_leg_score",-99))-diversity_penalty
                if gk not in best_by_game or score>best_by_game[gk][0]:
                    best_by_game[gk]=(score,y)
            legs_pool=[pair[1] for pair in sorted(best_by_game.values(),key=lambda pair:pair[0],reverse=True)]
            selected_legs=legs_pool[:parlay_legs]

            # Equilibrado/Mayor ganancia pueden completar con candidatos de otros juegos aunque sean amarillos.
            if len(selected_legs)<parlay_legs and parlay_profile!="Menor riesgo":
                current_games={x.get("game_pk") for x in selected_legs}
                fallback_by_game={}
                for y in enriched:
                    sig=_pick_signature(y)
                    gk=y.get("game_pk")
                    if gk in current_games: continue
                    if parlay_avoid_repeat and sig in used_signatures: continue
                    if y.get("parlay_leg_score",-99)<=-90: continue
                    if gk not in fallback_by_game or y.get("parlay_leg_score",-99)>fallback_by_game[gk].get("parlay_leg_score",-99):
                        fallback_by_game[gk]=y
                for y in sorted(fallback_by_game.values(),key=lambda z:z.get("parlay_leg_score",-99),reverse=True):
                    selected_legs.append(y)
                    current_games.add(y.get("game_pk"))
                    if len(selected_legs)>=parlay_legs: break

            if not selected_legs:
                break
            built.append({"legs":selected_legs,"requested":parlay_legs,"number":pidx+1})
            if parlay_avoid_repeat:
                used_signatures.update(_pick_signature(y) for y in selected_legs)

        st.session_state["v763_parlay_results"]={
            "parlays":built,"requested_parlays":parlay_count,"requested_legs":parlay_legs,"profile":parlay_profile,"markets":parlay_market_choices,
            "avoid_repeat":parlay_avoid_repeat,"eligible":len(eligible),"complete":complete,"pending":pending,"errors":perrors,"usage":usage,
            "generated":len(candidates),"time":nowp.strftime("%H:%M:%S")
        }
        # Evita mostrar un ticket viejo de V7.6.3 después de generar con la nueva lógica.
        st.session_state.pop("v761_parlay_result",None)

    pres=st.session_state.get("v763_parlay_results")
    if pres:
        parlays=pres.get("parlays",[])
        full_count=sum(1 for p in parlays if len(p.get("legs",[]))>=pres.get("requested_legs",0))
        st.caption(f"Última búsqueda: {pres.get('time','')} CDMX · {pres.get('eligible',0)} juegos elegibles · {pres.get('generated',0)} mercados generados")
        sm1,sm2,sm3=st.columns(3)
        sm1.metric("Parlays construidos",f"{len(parlays)}/{pres.get('requested_parlays',0)}")
        sm2.metric("Parlays completos",full_count)
        sm3.metric("Sin repetir picks","Sí" if pres.get("avoid_repeat") else "No")
        if len(parlays)<pres.get("requested_parlays",0) or full_count<len(parlays):
            st.warning("No fue posible completar todos los tickets exactamente como los pediste con la calidad/filtros actuales. No forcé selecciones peores solo para llenar espacios.")
        if not parlays:
            st.info("No hay suficientes selecciones para construir parlays con estos filtros. Prueba 'Completos o pendientes', más mercados o un perfil menos conservador.")
        else:
            for pidx,pdata in enumerate(parlays,1):
                legs=pdata.get("legs",[])
                title=f"Parlay {pidx} · {len(legs)}/{pdata.get('requested',pres.get('requested_legs',0))} juegos · {pres.get('profile')}"
                st.markdown(f"### 🎟️ {title}")
                if len(legs)<pdata.get("requested",0):
                    st.warning(f"Este ticket quedó con {len(legs)} de {pdata.get('requested',0)} piernas por falta de candidatos que cumplieran los filtros.")
                st.caption("Puedes cambiar línea, lado o momio en cada pierna. Después pulsa el botón de este ticket para recalcular probabilidades, Gate, Bet Quality y combinación.")

                edit_specs=[]
                for i,x in enumerate(legs,1):
                    gate=x.get("prebet_gate_v76",{})
                    status="🟢 Gate PASS" if gate.get("pass",False) else "🟡 Con riesgo"
                    st.markdown(f"**{i}. {x.get('game')} · {x.get('label')}**  \n{status} · Conservadora **{x.get('prob_low',x.get('prob',0))*100:.1f}%** · Confianza **{x.get('confidence_score',0):.0f}/100** · Bet Quality **{x.get('bet_quality_score',0):.0f}/100**")
                    default_odd=float(x.get("parlay_odds") or x.get("draftea_odds") or x.get("reference_odds") or x.get("model_target_odds") or 1.50)
                    keybase=f"v763_p{pidx}_leg{i}_{x.get('game_pk')}_{x.get('market_family')}"
                    if x.get("sample_values") is not None:
                        with st.expander(f"✏️ Editar Parlay {pidx} · pierna {i}: línea / lado / momio",expanded=False):
                            ec1,ec2,ec3=st.columns(3)
                            eside=ec1.selectbox("Lado",["over","under"],index=0 if x.get("side")=="over" else 1,format_func=lambda z:"Over / Más" if z=="over" else "Under / Menos",key=f"{keybase}_side")
                            eline=ec2.number_input("Línea Draftea",value=float(x.get("line",.5)),step=.5,key=f"{keybase}_line")
                            eodd=ec3.number_input("Momio Draftea",min_value=1.01,max_value=100.0,value=float(round(default_odd,2)),step=.01,key=f"{keybase}_odd")
                            preview=v7_reprice_line(x,eline,eside)
                            if preview:
                                ppm=v7_price_metrics(preview,eodd)
                                st.caption(f"Vista previa: central {preview.get('prob',0)*100:.1f}% · conservadora {preview.get('prob_low',0)*100:.1f}% · EV cons. {ppm.get('ev_cons',0)*100:+.1f}% · {ppm.get('verdict')}")
                    else:
                        eside=x.get("side"); eline=x.get("line")
                        eodd=st.number_input(f"Momio Draftea · Parlay {pidx} pierna {i}",min_value=1.01,max_value=100.0,value=float(round(default_odd,2)),step=.01,key=f"{keybase}_odd")
                    edit_specs.append({"base":x,"side":eside,"line":eline,"odds":float(eodd)})

                if st.button(f"🔄 Actualizar TODO el Parlay {pidx} con mis cambios",type="primary",use_container_width=True,key=f"v763_update_parlay_{pidx}"):
                    newlegs=[]
                    for spec in edit_specs:
                        base=spec["base"]
                        if base.get("sample_values") is not None and spec.get("line") is not None:
                            y=v7_reprice_line(base,float(spec["line"]),spec.get("side") or base.get("side","over")) or dict(base)
                            y["manual_line_edited"]=bool(float(spec["line"])!=float(base.get("line",spec["line"])) or spec.get("side")!=base.get("side"))
                        else:
                            y=dict(base)
                        y["reference_odds"]=None if y.get("manual_line_edited") else y.get("reference_odds")
                        y=refresh_pick_v762(y,use_odds=False,manual_odds=float(spec["odds"]))
                        y["parlay_odds"]=float(spec["odds"])
                        newlegs.append(y)
                    newpres=dict(pres); newparlays=[dict(z) for z in parlays]
                    newparlays[pidx-1]=dict(newparlays[pidx-1]); newparlays[pidx-1]["legs"]=newlegs
                    newpres["parlays"]=newparlays; newpres["time"]=now_cdmx().strftime("%H:%M:%S")
                    st.session_state["v763_parlay_results"]=newpres
                    st.success(f"Parlay {pidx} actualizado: recalculé cada pierna y los totales con tus líneas/momios nuevos.")
                    st.rerun()

                joint=1.0; combined=1.0
                for x in legs:
                    joint*=float(x.get("prob_low",x.get("prob",0)))
                    combined*=float(x.get("parlay_odds") or x.get("draftea_odds") or x.get("reference_odds") or x.get("model_target_odds") or 1.0)
                m1,m2,m3=st.columns(3)
                m1.metric("Momio combinado",f"{combined:.2f}x")
                m2.metric("Prob. conjunta conservadora",f"{joint*100:.1f}%")
                m3.metric("Retorno por $100",f"${combined*100:,.0f}")
                st.caption("La probabilidad conjunta es una aproximación multiplicando probabilidades conservadoras y asume independencia. Un parlay nunca es seguro; mercados correlacionados pueden cambiar el riesgo real.")

                with st.expander(f"🧪 Guardar Parlay {pidx} en Paper Bets",expanded=False):
                    st.caption("Se guarda como UNA sola apuesta. Las piernas quedan dentro del ticket para poder liquidarlo, pero el monto, ROI y resultado cuentan una sola vez.")
                    pstake=st.number_input("Monto simulado del parlay completo (MXN)",min_value=5.0,max_value=10000.0,value=50.0,step=5.0,key=f"v764_parlay_paper_stake_{pidx}")
                    if st.button(f"🧊 Guardar Parlay {pidx} completo en Paper Bets",use_container_width=True,key=f"v764_save_parlay_paper_{pidx}"):
                        rec=build_parlay_paper_record_v764(legs,pstake,selected_date,games,parlay_index=pidx)
                        if save_paper_record_v762(rec):
                            st.success(f"Parlay {pidx} guardado como 1 Paper Bet · {len(legs)} selecciones · {float(rec.get('odds',1)):.2f}x · ID {rec.get('paper_id')}.")
                        else:
                            st.warning("El parlay quedó en sesión, pero falló la persistencia externa/local.")
                st.divider()

        if pres.get("errors"):
            with st.expander("⚠️ Errores de análisis de Parlays",expanded=False):
                for e in pres["errors"]: st.write("• "+e)

with tab2:
    st.subheader("💵 Evaluar momios — usa exactamente lo que ajustaste en Express")
    express_eval=list(st.session_state.get("v7_express_results",[]))+list(st.session_state.get("v724_express_fallback",[]))
    source_is_express=bool(express_eval)
    source_candidates=express_eval if source_is_express else (ranked_auto if st.session_state.get("v653_analysis_ready",False) else [])

    if source_is_express:
        st.success("Usando el Top de Express. Si editaste una línea y pulsaste **Actualizar TODO Express**, aquí aparece ya recalculada.")
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
                    "model_version":"V7.5",
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
        st.info("Aún no hay Paper Bets. Puedes guardarlas desde **Express**, **Parlays** o **Evaluar momios**.")
    else:
        if st.button("🔄 Actualizar resultados desde MLB",type="primary",key="settle_paper_v65"):
            st.cache_data.clear()
            updated=0
            for rec in st.session_state["v653_paper_bets"]:
                if rec.get("result") in ("WON","LOST","PUSH"):
                    continue
                if rec.get("record_type")=="PARLAY" or rec.get("market_family")=="parlay":
                    verdict,note,leg_states=settle_parlay_record_v764(rec)
                    rec["result"]=verdict; rec["settlement_note"]=note; rec["leg_results"]=leg_states
                    if verdict in ("WON","LOST","PUSH"):
                        rec["status"]="SETTLED"
                    persistent_upsert_paper_bet(rec); updated+=1
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
            if rec.get("record_type")=="PARLAY" or rec.get("market_family")=="parlay":
                legs=rec.get("legs") or []
                st.write(
                    f"**🎟️ {icon} {rec.get('game')} @ {float(rec.get('odds',0)):.2f}x** — "
                    f"apuesta ${float(rec.get('stake_mxn',0)):,.2f} MXN | retorno potencial ${float(rec.get('stake_mxn',0))*float(rec.get('odds',0)):,.2f} MXN | "
                    f"{rec.get('result','PENDING')}"
                )
                with st.expander(f"▶ Ver {len(legs)} selecciones",expanded=False):
                    leg_results={f"{x.get('game')}|{x.get('market')}":x for x in (rec.get('leg_results') or [])}
                    for j,leg in enumerate(legs,1):
                        lr=leg_results.get(f"{leg.get('game')}|{leg.get('market')}",{})
                        li={"WON":"✅","LOST":"❌","PUSH":"↩️","PENDING":"⏳","UNSUPPORTED":"⚠️"}.get(lr.get("result"),"⏳")
                        st.write(f"{j}. {li} **{leg.get('game')} · {leg.get('market')}** @ {float(leg.get('odds',0)):.2f}x" + (f" — {lr.get('note')}" if lr.get('note') else ""))
            else:
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
            if rec.get("paper_source"):
                _src=f"Origen: {rec.get('paper_source')}"
                if rec.get("paper_group_id"): _src+=f" · Grupo {rec.get('paper_group_id')}"
                st.caption(_src)
            if rec.get("settlement_note"):
                st.caption(rec["settlement_note"])

            _pid=str(rec.get("paper_id", ""))
            if st.session_state.get("v762_delete_confirm") == _pid:
                _dc1,_dc2=st.columns(2)
                if _dc1.button("✅ Sí, borrar esta Paper Bet",key=f"v762_del_yes_{_pid}",use_container_width=True):
                    st.session_state["v653_paper_bets"]=[r for r in st.session_state.get("v653_paper_bets",[]) if str(r.get("paper_id"))!=_pid]
                    persistent_delete_paper_bet(_pid)
                    st.session_state.pop("v762_delete_confirm",None)
                    st.rerun()
                if _dc2.button("Cancelar",key=f"v762_del_no_{_pid}",use_container_width=True):
                    st.session_state.pop("v762_delete_confirm",None)
                    st.rerun()
            else:
                if st.button("🗑️ Borrar solo esta Paper Bet",key=f"v762_del_one_{_pid}"):
                    st.session_state["v762_delete_confirm"]=_pid
                    st.rerun()

        fields=[
            "paper_id","timestamp","freeze_time_iso","hours_to_game_at_freeze","model_version","date","game_pk","game","game_time_cdmx",
            "away_abbr","home_abbr","market","category","odds","stake","stake_mxn","unit_value_mxn",
            "prob_central","prob_low","prob_high","confidence","agreement","confirmed","away_lineup_confirmed","home_lineup_confirmed","both_lineups_confirmed","away_lineup_count","home_lineup_count",
            "data_quality","readiness","readiness_level","freeze_type","status","result","settlement_note",
            "paper_source","paper_group_id","record_type","leg_count","legs_json","leg_results_json","manual_line_edited","line","side","market_family","subject","bet_quality_score","market_reliability"
        ]
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        export_rows=[]
        for _r in bets:
            _e=dict(_r)
            _e["legs_json"]=json.dumps(_e.pop("legs",[]),ensure_ascii=False,default=str)
            _e["leg_results_json"]=json.dumps(_e.pop("leg_results",[]),ensure_ascii=False,default=str)
            export_rows.append(_e)
        writer.writerows(export_rows)
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
    "V7.5 ALPHA. Alta probabilidad no significa apuesta segura. El objetivo es elevar selección y calibración, no prometer un porcentaje fijo de aciertos. "
    "Paper Betting debe validar el modelo antes de aumentar riesgo real."
)