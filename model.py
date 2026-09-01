import math

LEAGUE_RPG = 4.40
LEAGUE_ERA = 4.20
LEAGUE_WHIP = 1.28
LEAGUE_K9 = 8.60
LEAGUE_BB9 = 3.20
LEAGUE_HR9 = 1.20
BASE_F5_RUNS_PER_TEAM = LEAGUE_RPG * (5/9)

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def no_vig_probs(odds_a, odds_b):
    a = 1/odds_a
    b = 1/odds_b
    total = a+b
    return a/total, b/total, total-1

def expected_value_decimal(p, odds):
    return p*odds - 1

def prob_to_decimal(p):
    return (1/p) if p > 0 else float("inf")

def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam**k) / math.factorial(k)

def weather_factor(weather):
    if not weather:
        return 1.0

    factor = 1.0
    temp = weather.get("temp_f", 72)
    humidity = weather.get("humidity", 50)
    wind = weather.get("wind_mph", 5)

    # Ajustes deliberadamente pequeños para evitar sobrepeso del clima.
    if temp >= 90:
        factor += 0.025
    elif temp >= 82:
        factor += 0.015
    elif temp <= 50:
        factor -= 0.020
    elif temp <= 58:
        factor -= 0.010

    if humidity >= 75:
        factor += 0.005

    if wind >= 15:
        factor += 0.010

    return clamp(factor, 0.95, 1.06)

def pitcher_quality_factor(p):
    if not p:
        return 1.0

    era = clamp(p["era"]/LEAGUE_ERA, 0.65, 1.55)
    whip = clamp(p["whip"]/LEAGUE_WHIP, 0.75, 1.40)

    # Más K reduce carreras; más BB y HR las aumenta.
    k = clamp(LEAGUE_K9/max(p["k9"], 0.1), 0.80, 1.20)
    bb = clamp(p["bb9"]/LEAGUE_BB9, 0.75, 1.30)
    hr = clamp(p["hr9"]/LEAGUE_HR9, 0.70, 1.40)

    raw = (
        0.38*era +
        0.22*whip +
        0.16*k +
        0.10*bb +
        0.14*hr
    )

    # Reduce sobreajuste con muestras pequeñas.
    gs = p.get("games_started", 0)
    sample = clamp(gs/14, 0.30, 1.0)
    return 1 + (raw - 1)*sample

def project_f5_runs_v3(offense, opposing_pitcher, park_factor=1.0, weather=None):
    blended_rpg = 0.70*offense["season_rpg"] + 0.30*offense["recent_rpg"]
    offense_factor = clamp(blended_rpg/LEAGUE_RPG, 0.70, 1.35)

    pitcher_factor = pitcher_quality_factor(opposing_pitcher)
    park_adj = clamp(park_factor, 0.92, 1.12)
    weather_adj = weather_factor(weather)

    projected = (
        BASE_F5_RUNS_PER_TEAM
        * offense_factor
        * pitcher_factor
        * park_adj
        * weather_adj
    )

    projected = clamp(projected, 0.60, 4.50)

    debug = {
        "base_f5": round(BASE_F5_RUNS_PER_TEAM, 3),
        "season_rpg": round(offense["season_rpg"], 3),
        "recent_15_rpg": round(offense["recent_rpg"], 3),
        "blended_rpg": round(blended_rpg, 3),
        "offense_factor": round(offense_factor, 3),
        "pitcher_factor": round(pitcher_factor, 3),
        "park_factor": round(park_adj, 3),
        "weather_factor": round(weather_adj, 3),
        "projected_runs": round(projected, 3),
    }
    return projected, debug

def total_probabilities(lambda_total, line):
    under = over = push = 0.0

    for k in range(0, 22):
        p = poisson_pmf(k, lambda_total)
        if k < line:
            under += p
        elif k > line:
            over += p
        else:
            push += p

    total = under + over + push
    if total:
        under /= total
        over /= total
        push /= total

    if abs(line - round(line)) < 1e-9 and (under+over)>0:
        under = under/(under+over)
        over = over/(under+over)

    return {"under":under, "over":over, "push":push}

def moneyline_probabilities(lambda_away, lambda_home, max_runs=16):
    away = home = tie = 0.0

    for a in range(max_runs+1):
        pa = poisson_pmf(a, lambda_away)
        for h in range(max_runs+1):
            ph = poisson_pmf(h, lambda_home)
            p = pa*ph

            if a>h:
                away += p
            elif h>a:
                home += p
            else:
                tie += p

    total = away+home+tie
    if total:
        away/=total
        home/=total
        tie/=total

    return {"away":away, "home":home, "tie":tie}

def grade_pick(ev, edge, data_quality):
    if data_quality < 60:
        return "PASS", "Baja"

    if ev >= 0.12 and edge >= 0.06 and data_quality >= 85:
        return "STRONG", "Alta"
    if ev >= 0.06 and edge >= 0.035 and data_quality >= 75:
        return "PLAY", "Media-Alta"
    if ev >= 0.02 and edge >= 0.015 and data_quality >= 65:
        return "LEAN", "Media"

    return "PASS", "Baja"
