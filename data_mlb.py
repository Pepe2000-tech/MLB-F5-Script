from datetime import datetime, timedelta
import requests
import streamlit as st

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "MLB-F5-Model/3.0"}

# Factor >1 favorece carreras; <1 las reduce.
STADIUMS = {
    "ARI": {"lat": 33.4455, "lon": -112.0667, "factor": 1.03, "name": "Chase Field"},
    "ATL": {"lat": 33.8907, "lon": -84.4677, "factor": 1.01, "name": "Truist Park"},
    "BAL": {"lat": 39.2839, "lon": -76.6217, "factor": 0.97, "name": "Camden Yards"},
    "BOS": {"lat": 42.3467, "lon": -71.0972, "factor": 1.05, "name": "Fenway Park"},
    "CHC": {"lat": 41.9484, "lon": -87.6553, "factor": 1.03, "name": "Wrigley Field"},
    "CWS": {"lat": 41.8300, "lon": -87.6338, "factor": 1.01, "name": "Rate Field"},
    "CIN": {"lat": 39.0979, "lon": -84.5082, "factor": 1.08, "name": "Great American Ball Park"},
    "CLE": {"lat": 41.4962, "lon": -81.6852, "factor": 0.97, "name": "Progressive Field"},
    "COL": {"lat": 39.7559, "lon": -104.9942, "factor": 1.14, "name": "Coors Field"},
    "DET": {"lat": 42.3390, "lon": -83.0485, "factor": 0.98, "name": "Comerica Park"},
    "HOU": {"lat": 29.7573, "lon": -95.3555, "factor": 1.00, "name": "Daikin Park"},
    "KC": {"lat": 39.0517, "lon": -94.4803, "factor": 0.97, "name": "Kauffman Stadium"},
    "LAA": {"lat": 33.8003, "lon": -117.8827, "factor": 0.98, "name": "Angel Stadium"},
    "LAD": {"lat": 34.0739, "lon": -118.2400, "factor": 1.00, "name": "Dodger Stadium"},
    "MIA": {"lat": 25.7781, "lon": -80.2197, "factor": 0.96, "name": "loanDepot park"},
    "MIL": {"lat": 43.0280, "lon": -87.9712, "factor": 1.01, "name": "American Family Field"},
    "MIN": {"lat": 44.9817, "lon": -93.2776, "factor": 0.99, "name": "Target Field"},
    "NYM": {"lat": 40.7571, "lon": -73.8458, "factor": 0.97, "name": "Citi Field"},
    "NYY": {"lat": 40.8296, "lon": -73.9262, "factor": 1.04, "name": "Yankee Stadium"},
    "ATH": {"lat": 38.5803, "lon": -121.5130, "factor": 1.00, "name": "Sutter Health Park"},
    "PHI": {"lat": 39.9061, "lon": -75.1665, "factor": 1.04, "name": "Citizens Bank Park"},
    "PIT": {"lat": 40.4469, "lon": -80.0057, "factor": 0.96, "name": "PNC Park"},
    "SD": {"lat": 32.7076, "lon": -117.1570, "factor": 0.94, "name": "Petco Park"},
    "SF": {"lat": 37.7786, "lon": -122.3893, "factor": 0.95, "name": "Oracle Park"},
    "SEA": {"lat": 47.5914, "lon": -122.3325, "factor": 0.96, "name": "T-Mobile Park"},
    "STL": {"lat": 38.6226, "lon": -90.1928, "factor": 0.98, "name": "Busch Stadium"},
    "TB": {"lat": 27.7683, "lon": -82.6534, "factor": 0.97, "name": "George M. Steinbrenner Field"},
    "TEX": {"lat": 32.7473, "lon": -97.0847, "factor": 1.00, "name": "Globe Life Field"},
    "TOR": {"lat": 43.6414, "lon": -79.3894, "factor": 1.01, "name": "Rogers Centre"},
    "WSH": {"lat": 38.8730, "lon": -77.0074, "factor": 0.99, "name": "Nationals Park"},
}

def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300)
def get_schedule(date_str):
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher,team,venue",
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

            game_time_local = None
            if g.get("gameDate"):
                try:
                    game_time_local = g["gameDate"]
                except Exception:
                    pass

            games.append({
                "game_pk": g.get("gamePk"),
                "away_id": away.get("id"),
                "home_id": home.get("id"),
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_pitcher_id": away_pp.get("id"),
                "home_pitcher_id": home_pp.get("id"),
                "away_pitcher_name": away_pp.get("fullName", "TBD"),
                "home_pitcher_name": home_pp.get("fullName", "TBD"),
                "label": f"{away_abbr} @ {home_abbr}",
                "game_time_local": game_time_local,
            })
    return games

@st.cache_data(ttl=1800)
def get_pitcher_stats(player_id, season):
    if not player_id:
        return None

    params = {"stats": "season", "group": "pitching", "season": season}
    try:
        data = _get(f"{BASE}/people/{player_id}/stats", params=params)
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None

        stat = splits[0].get("stat", {})
        ip = float(stat.get("inningsPitched", 0) or 0)
        so = float(stat.get("strikeOuts", 0) or 0)
        bb = float(stat.get("baseOnBalls", 0) or 0)
        hr = float(stat.get("homeRuns", 0) or 0)

        return {
            "era": float(stat.get("era", 4.20) or 4.20),
            "whip": float(stat.get("whip", 1.28) or 1.28),
            "innings": ip,
            "games_started": int(stat.get("gamesStarted", 0) or 0),
            "k9": (so * 9 / ip) if ip > 0 else 8.5,
            "bb9": (bb * 9 / ip) if ip > 0 else 3.2,
            "hr9": (hr * 9 / ip) if ip > 0 else 1.2,
        }
    except Exception:
        return None

@st.cache_data(ttl=1800)
def get_team_form(team_id, target_date):
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    season_start = target.replace(month=3, day=20)
    end = target - timedelta(days=1)

    fallback = {
        "season_rpg": 4.40,
        "recent_rpg": 4.40,
        "games": 0,
        "recent_games": 0,
    }

    if end < season_start:
        return fallback

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
        return fallback

    rows = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
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
                rows.append(float(runs))

    if not rows:
        return fallback

    season_rpg = sum(rows) / len(rows)
    recent = rows[-15:]
    recent_rpg = sum(recent) / len(recent)

    return {
        "season_rpg": season_rpg,
        "recent_rpg": recent_rpg,
        "games": len(rows),
        "recent_games": len(recent),
    }

def get_stadium_context(home_abbr):
    return STADIUMS.get(home_abbr)

@st.cache_data(ttl=1800)
def get_weather(lat, lon, date_str, game_time=None):
    # Open-Meteo no requiere API key.
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation_probability",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "start_date": date_str,
            "end_date": date_str,
        }

        data = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=15,
        ).json()

        hourly = data.get("hourly", {})
        temps = hourly.get("temperature_2m", [])
        hum = hourly.get("relative_humidity_2m", [])
        wind = hourly.get("wind_speed_10m", [])
        precip = hourly.get("precipitation_probability", [])

        if not temps:
            return None

        # Como primera aproximación usamos la hora más cálida de la tarde si
        # no tenemos una hora local fiable del estadio.
        idx = min(range(len(temps)), key=lambda i: abs(i - 18))

        temp_f = float(temps[idx])
        humidity = float(hum[idx]) if idx < len(hum) else 50
        wind_mph = float(wind[idx]) if idx < len(wind) else 5
        pop = float(precip[idx]) if idx < len(precip) else 0

        summary = "neutral"
        if temp_f >= 85:
            summary = "caluroso"
        elif temp_f <= 55:
            summary = "frío"

        return {
            "temp_f": temp_f,
            "humidity": humidity,
            "wind_mph": wind_mph,
            "precip_probability": pop,
            "summary": summary,
        }
    except Exception:
        return None
