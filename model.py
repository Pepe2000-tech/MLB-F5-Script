import math

LEAGUE_RPG=4.40; LEAGUE_ERA=4.20; LEAGUE_WHIP=1.28
LEAGUE_K9=8.60; LEAGUE_BB9=3.20; LEAGUE_HR9=1.20; LEAGUE_OPS=.720
BASE_F5=LEAGUE_RPG*(5/9); BASE_REST=LEAGUE_RPG*(4/9)

def clamp(x,lo,hi):return max(lo,min(hi,x))
def no_vig_probs(a,b):
    ia,ib=1/a,1/b;t=ia+ib
    return ia/t,ib/t,t-1
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
        "home_staff_factor":round(home_bp,3),"away_staff_factor":round(away_bp,3),
        "park_factor":round(park,3),"weather_factor":round(wf,3),
        "away_full":round(away,3),"home_full":round(home,3)
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

def grade_market(ev,edge,dq,confirmed,allow_strong=True):
    if dq<55:return "PASS","Baja"
    if not confirmed:
        if ev>=.07 and edge>=.04 and dq>=68:return "PLAY","Provisional"
        if ev>=.025 and edge>=.015 and dq>=58:return "LEAN","Provisional"
        return "PASS","Provisional"
    if allow_strong and ev>=.14 and edge>=.07 and dq>=85:return "STRONG","Alta"
    if ev>=.07 and edge>=.04 and dq>=72:return "PLAY","Media-Alta"
    if ev>=.025 and edge>=.015 and dq>=62:return "LEAN","Media"
    return "PASS","Baja"

def poisson_tail(lam,threshold):
    if threshold<=0:return 1.0
    return 1-sum(poisson_pmf(k,lam) for k in range(threshold))

def poisson_under(lam,max_count):
    return sum(poisson_pmf(k,lam) for k in range(max_count+1))

def prob_at_least_one(rate,pa):
    rate=clamp(rate,0,.95)
    return 1-(1-rate)**pa

def expected_pa(order):
    return {1:4.55,2:4.50,3:4.45,4:4.35,5:4.25,6:4.10,7:4.00,8:3.90,9:3.80}.get(order,4.10)

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
            for th in [4,5,6,7]:
                prob=poisson_tail(mean_k,th)
                props.append({
                    "category":"Pitcher Ks","label":f"{name} {th}+ ponches","prob":prob,
                    "safety":round(clamp(prob*100+(8 if th<=5 else 0),30,92)),
                    "reason":f"Media proyectada ~{mean_k:.1f} K; K-rate rival ajustado.",
                    "confirmed":True,"data_quality":78
                })
            # O/U 4.5 y 5.5
            for line in [4.5,5.5]:
                over_th=int(math.floor(line))+1
                p_over=poisson_tail(mean_k,over_th)
                p_under=1-p_over
                props += [
                    {"category":"Pitcher Ks O/U","label":f"{name} Over {line} K","prob":p_over,
                     "safety":round(clamp(p_over*100,30,88)),"reason":f"Media proyectada ~{mean_k:.1f} K.",
                     "confirmed":True,"data_quality":78},
                    {"category":"Pitcher Ks O/U","label":f"{name} Under {line} K","prob":p_under,
                     "safety":round(clamp(p_under*100,30,88)),"reason":f"Media proyectada ~{mean_k:.1f} K.",
                     "confirmed":True,"data_quality":78},
                ]

    def add_hitters(lineup):
        for p in lineup[:9]:
            if not p.get("stats_available"):continue
            pa=expected_pa(p["order"])
            confirmed=lineups_confirmed
            dq=82 if confirmed else 62

            mean_hits=p["hit_rate"]*pa
            for th in [1,2]:
                prob=poisson_tail(mean_hits,th)
                props.append({"category":"Hits","label":f"{p['name']} {th}+ hit{'s' if th>1 else ''}",
                              "prob":prob,"safety":round(clamp(prob*100,25,95)),
                              "reason":f"Media hits ~{mean_hits:.2f}; ~{pa:.1f} PA esperadas desde turno #{p['order']}.",
                              "confirmed":confirmed,"data_quality":dq})
            # Hits O/U 1.5
            p_over=poisson_tail(mean_hits,2)
            props += [
                {"category":"Hits","label":f"{p['name']} Over 1.5 hits","prob":p_over,
                 "safety":round(clamp(p_over*100,20,85)),"reason":f"Media hits ~{mean_hits:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
                {"category":"Hits","label":f"{p['name']} Under 1.5 hits","prob":1-p_over,
                 "safety":round(clamp((1-p_over)*100,30,92)),"reason":f"Media hits ~{mean_hits:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
            ]

            mean_tb=p["tb_rate"]*pa
            for th in [1,2,3]:
                prob=poisson_tail(mean_tb,th)
                props.append({"category":"Total Bases","label":f"{p['name']} {th}+ bases totales",
                              "prob":prob,"safety":round(clamp(prob*100,20,95)),
                              "reason":f"Media TB ~{mean_tb:.2f}; posición #{p['order']}.",
                              "confirmed":confirmed,"data_quality":dq})
            p_tb_over=poisson_tail(mean_tb,2)
            props += [
                {"category":"Total Bases","label":f"{p['name']} Over 1.5 bases totales","prob":p_tb_over,
                 "safety":round(clamp(p_tb_over*100,20,88)),"reason":f"Media TB ~{mean_tb:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
                {"category":"Total Bases","label":f"{p['name']} Under 1.5 bases totales","prob":1-p_tb_over,
                 "safety":round(clamp((1-p_tb_over)*100,25,90)),"reason":f"Media TB ~{mean_tb:.2f}.",
                 "confirmed":confirmed,"data_quality":dq},
            ]

            mean_hrr=p["hrr_rate"]*pa
            for th in [2,3]:
                prob=poisson_tail(mean_hrr,th)
                props.append({"category":"HRR","label":f"{p['name']} {th}+ HRR","prob":prob,
                              "safety":round(clamp(prob*100,20,88)),
                              "reason":f"Media aproximada H+R+RBI ~{mean_hrr:.2f}.",
                              "confirmed":confirmed,"data_quality":dq})

            hrp=prob_at_least_one(p["hr_rate"],pa)
            props.append({"category":"Home Run","label":f"{p['name']} 1+ HR","prob":hrp,
                          "safety":round(clamp(hrp*100,10,70)),
                          "reason":f"Mercado volátil; HR/PA con ~{pa:.1f} PA esperadas.",
                          "confirmed":confirmed,"data_quality":max(50,dq-10)})

    add_hitters(away_lineup);add_hitters(home_lineup)
    return props

def evaluate_prop_odds(prop,odds):
    p=prop["prob"];ev=p*odds-1;fair=prob_to_decimal(p)
    implied=1/odds;edge=p-implied
    verdict,conf=grade_market(ev,edge,prop.get("data_quality",65),prop.get("confirmed",False),allow_strong=False)
    return {"ev":ev,"fair_odds":fair,"edge":edge,"verdict":verdict,"confidence":conf}
