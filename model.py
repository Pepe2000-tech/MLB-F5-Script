import math

LEAGUE_RPG = 4.40
LEAGUE_ERA = 4.20
LEAGUE_WHIP = 1.28
BASE_F5_RUNS_PER_TEAM = LEAGUE_RPG * (5 / 9)

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def decimal_to_implied(odds):
    return 1 / odds

def prob_to_decimal(p):
    if p <= 0:
        return float("inf")
    return 1 / p

def no_vig_probs(under_odds, over_odds):
    u = 1 / under_odds
    o = 1 / over_odds
    total = u + o
    return u / total, o / total, total - 1

def expected_value_decimal(p, odds):
    return p * odds - 1

def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def project_f5_runs(offense, opposing_pitcher, pitcher_confirmed=True):
    blended_rpg = 0.72 * offense["season_rpg"] + 0.28 * offense["recent_rpg"]
    offense_factor = clamp(blended_rpg / LEAGUE_RPG, 0.68, 1.38)

    if opposing_pitcher:
        era_factor = clamp(opposing_pitcher["era"] / LEAGUE_ERA, 0.65, 1.55)
        whip_factor = clamp(opposing_pitcher["whip"] / LEAGUE_WHIP, 0.75, 1.40)
        pitcher_factor = 0.72 * era_factor + 0.28 * whip_factor

        gs = opposing_pitcher.get("games_started", 0)
        sample_weight = clamp(gs / 12, 0.25, 1.0)
        pitcher_factor = 1 + (pitcher_factor - 1) * sample_weight
    else:
        pitcher_factor = 1.0

    if not pitcher_confirmed:
        pitcher_factor = 1 + (pitcher_factor - 1) * 0.35

    projected = BASE_F5_RUNS_PER_TEAM * offense_factor * pitcher_factor
    projected = clamp(projected, 0.65, 4.25)

    return projected, {
        "base_f5_runs": round(BASE_F5_RUNS_PER_TEAM, 3),
        "season_rpg": round(offense["season_rpg"], 3),
        "recent_15_rpg": round(offense["recent_rpg"], 3),
        "blended_rpg": round(blended_rpg, 3),
        "offense_factor": round(offense_factor, 3),
        "pitcher_factor": round(pitcher_factor, 3),
        "projected_runs": round(projected, 3),
    }

def total_probabilities(lambda_total, line):
    under = over = push = 0.0

    for k in range(0, 21):
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

    if abs(line - round(line)) < 1e-9 and (under + over) > 0:
        under_no_push = under / (under + over)
        over_no_push = over / (under + over)
    else:
        under_no_push = under
        over_no_push = over

    return {"under": under_no_push, "over": over_no_push, "push": push}

def moneyline_probabilities(lambda_away, lambda_home, max_runs=15):
    away = home = tie = 0.0
    for a in range(max_runs + 1):
        pa = poisson_pmf(a, lambda_away)
        for h in range(max_runs + 1):
            ph = poisson_pmf(h, lambda_home)
            p = pa * ph
            if a > h:
                away += p
            elif h > a:
                home += p
            else:
                tie += p

    total = away + home + tie
    if total:
        away /= total
        home /= total
        tie /= total
    return {"away": away, "home": home, "tie": tie}
