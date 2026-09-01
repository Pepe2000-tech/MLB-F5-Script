from datetime import datetime, timedelta
import requests
import streamlit as st

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "MLB-F5-Model/2.0"}

def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300)
def get_schedule(date_str):
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher,team",
    }
    try:
        data = _get(f"{BASE}/schedule", params=params)
    except Exception:
        return []

    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            away = teams.get("away", {}).get("team", {})
            home = teams.get("home", {}).get("team", {})

            away_pp = teams.get("away", {}).get("probablePitcher") or {}
            home_pp = teams.get("home", {}).get("probablePitcher") or {}

            away_abbr = away.get("abbreviation") or away.get("teamName") or "AWAY"
            home_abbr = home.get("abbreviation") or home.get("teamName") or "HOME"

            games.append({
                "game_pk": g.get("gamePk"),
                "away_id": away.get("id"),
                "home_id": home.get("id"),
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_name": away.get("name", away_abbr),
                "home_name": home.get("name", home_abbr),
                "away_pitcher_id": away_pp.get("id"),
                "home_pitcher_id": home_pp.get("id"),
                "away_pitcher_name": away_pp.get("fullName", "TBD"),
                "home_pitcher_name": home_pp.get("fullName", "TBD"),
                "label": f"{away_abbr} @ {home_abbr}",
            })
    return games

@st.cache_data(ttl=1800)
def get_pitcher_stats(player_id, season):
    if not player_id:
        return None
    params = {
        "stats": "season",
        "group": "pitching",
        "season": season,
    }
    try:
        data = _get(f"{BASE}/people/{player_id}/stats", params=params)
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        stat = splits[0].get("stat", {})
        return {
            "era": float(stat.get("era", 4.40)),
            "whip": float(stat.get("whip", 1.30)),
            "innings": float(stat.get("inningsPitched", 0) or 0),
            "games_started": int(stat.get("gamesStarted", 0) or 0),
        }
    except Exception:
        return None

@st.cache_data(ttl=1800)
def get_team_form(team_id, target_date):
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    season_start = target.replace(month=3, day=20)
    end = target - timedelta(days=1)

    if end < season_start:
        return {
            "season_rpg": 4.40,
            "recent_rpg": 4.40,
            "games": 0,
            "recent_games": 0,
        }

    params = {
        "sportId": 1,
        "teamId": team_id,
        "startDate": season_start.isoformat(),
        "endDate": end.isoformat(),
        "gameType": "R",
    }

    try:
        data = _get(f"{BASE}/schedule", params=params)
    except Exception:
        return {
            "season_rpg": 4.40,
            "recent_rpg": 4.40,
            "games": 0,
            "recent_games": 0,
        }

    rows = []
    for d in data.get("dates", []):
        game_date = d.get("date")
        for g in d.get("games", []):
            status = g.get("status", {}).get("abstractGameState")
            if status != "Final":
                continue

            teams = g.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})

            if away.get("team", {}).get("id") == team_id:
                runs = away.get("score")
            elif home.get("team", {}).get("id") == team_id:
                runs = home.get("score")
            else:
                continue

            if runs is not None:
                rows.append((game_date, float(runs)))

    if not rows:
        return {
            "season_rpg": 4.40,
            "recent_rpg": 4.40,
            "games": 0,
            "recent_games": 0,
        }

    season_rpg = sum(r for _, r in rows) / len(rows)
    recent = rows[-15:]
    recent_rpg = sum(r for _, r in recent) / len(recent)

    return {
        "season_rpg": season_rpg,
        "recent_rpg": recent_rpg,
        "games": len(rows),
        "recent_games": len(recent),
    }
