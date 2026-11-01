"""Public football-data.co.uk CSV research, no API key required.
Results/form only; no injuries or lineups. Fail closed on ambiguous names.
"""
from datetime import datetime, timezone
from difflib import SequenceMatcher
from io import StringIO
import re
import requests
import pandas as pd

LEAGUES = {'E0':'England Premier League','E1':'England Championship','E2':'England League One',
'E3':'England League Two','SC0':'Scotland Premiership','D1':'Germany Bundesliga',
'D2':'Germany 2. Bundesliga','I1':'Italy Serie A','I2':'Italy Serie B',
'SP1':'Spain La Liga','SP2':'Spain Segunda','F1':'France Ligue 1','F2':'France Ligue 2',
'N1':'Netherlands Eredivisie','B1':'Belgium First Division','P1':'Portugal Primeira Liga'}
class PublicResearchError(RuntimeError): pass

def clean(name):
    name=str(name).casefold().strip()
    aliases={'man utd':'man united','manchester utd':'man united','inter milan':'inter',
             'ac milan':'milan','paris saint germain':'paris sg','psg':'paris sg',
             'athletic bilbao':'ath bilbao','real sociedad':'sociedad',
             'bayern munich':'bayern munich','bayern münchen':'bayern munich',
             'borussia dortmund':'dortmund','newcastle united':'newcastle',
             'tottenham hotspur':'tottenham','west ham united':'west ham'}
    name=re.sub(r'[^\w ]+',' ',name)
    name=re.sub(r'\s+',' ',name).strip()
    return aliases.get(name,name)

def seasons(date):
    year=date.year if date.month>=7 else date.year-1
    return [f'{(y%100):02d}{((y+1)%100):02d}' for y in (year,year-1)]

def load_results(session=None,now=None,divisions=None):
    now=now or datetime.now(timezone.utc)
    client=session or requests.Session()
    data=[]; warnings=[]
    for season in seasons(now):
        for division in (divisions or LEAGUES):
            url=f'https://www.football-data.co.uk/mmz4281/{season}/{division}.csv'
            try:
                r=client.get(url,timeout=8,headers={'User-Agent':'QuantPoolPro/1.0'})
                r.raise_for_status()
                df=pd.read_csv(StringIO(r.content.decode('utf-8-sig',errors='replace')),on_bad_lines='skip')
                if not {'HomeTeam','AwayTeam','FTHG','FTAG'}.issubset(df.columns):
                    raise ValueError('missing required result columns')
                df=df[['HomeTeam','AwayTeam','FTHG','FTAG','Date']].copy()
                df['Date']=pd.to_datetime(df['Date'],dayfirst=True,errors='coerce')
                for col in ('FTHG','FTAG'): df[col]=pd.to_numeric(df[col],errors='coerce')
                df=df.dropna(subset=['HomeTeam','AwayTeam','FTHG','FTAG','Date'])
                df=df[df['Date']<pd.Timestamp(now.date())]
                df['division']=division
                data.append(df)
            except (requests.RequestException,ValueError,KeyError,UnicodeError, pd.errors.ParserError) as exc:
                warnings.append(f'{division} {season}: {type(exc).__name__}')
    if not data: raise PublicResearchError('Inga resultat kunde hämtas från football-data.co.uk')
    return pd.concat(data,ignore_index=True).drop_duplicates(),warnings

def resolve(name,teams):
    key=clean(name)
    exact=[x for x in teams if clean(x)==key]
    if len(exact)==1:return exact[0]
    scores=sorted(((SequenceMatcher(None,key,clean(t)).ratio(),t) for t in teams),reverse=True)
    if scores and scores[0][0]>=0.91 and (len(scores)==1 or scores[0][0]-scores[1][0]>=0.12):
        return scores[0][1]
    return None

def analyze_match(home,away,results,limit=10):
    teams=set(results['HomeTeam']).union(results['AwayTeam'])
    h=resolve(home,teams); a=resolve(away,teams)
    result={'home':home,'away':away,'matched_home':h,'matched_away':a,
            'source':'football-data.co.uk','status':'unavailable',
            'injuries':'not verified','suspensions':'not verified','lineups':'not verified'}
    if not h or not a:
        result['reason']='Lag kunde inte matchas entydigt i tillgängliga ligor'
        return result
    if h==a:
        result['reason']='Båda lag matchades till samma namn'
        return result
    def form(team,venue=None):
        rows=results[(results.HomeTeam==team)|(results.AwayTeam==team)]
        if venue=='home':rows=rows[rows.HomeTeam==team]
        if venue=='away':rows=rows[rows.AwayTeam==team]
        rows=rows.sort_values('Date',ascending=False).head(limit)
        played=[]
        for _,r in rows.iterrows():
            at_home=r.HomeTeam==team
            gf=int(r.FTHG if at_home else r.FTAG)
            ga=int(r.FTAG if at_home else r.FTHG)
            played.append({'date':str(r.Date.date()),'opponent':r.AwayTeam if at_home else r.HomeTeam,
                           'result':'W' if gf>ga else 'D' if gf==ga else 'L','gf':gf,'ga':ga})
        n=len(played)
        return {'games':n,'points_per_game':round(sum(3 if x['result']=='W' else 1 if x['result']=='D' else 0 for x in played)/n,2) if n else None,
                'goals_for_per_game':round(sum(x['gf'] for x in played)/n,2) if n else None,
                'goals_against_per_game':round(sum(x['ga'] for x in played)/n,2) if n else None,
                'matches':played}
    h2h=results[((results.HomeTeam==h)&(results.AwayTeam==a))|((results.HomeTeam==a)&(results.AwayTeam==h))].sort_values('Date',ascending=False).head(5)
    result.update(status='ok',home_form=form(h),away_form=form(a),home_at_home=form(h,'home'),away_at_away=form(a,'away'),
                  h2h=[{'date':str(r.Date.date()),'home':r.HomeTeam,'away':r.AwayTeam,'score':f'{int(r.FTHG)}-{int(r.FTAG)}'} for _,r in h2h.iterrows()])
    return result
