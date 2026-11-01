"""Public results research (no API key). Intended for personal use.

Uses football-data.co.uk season CSV and its separate worldwide CSV series.
No injury, suspension, or lineup verification. Ambiguous team matches fail closed.
"""
from datetime import datetime, timezone
from difflib import SequenceMatcher
from io import BytesIO
import re
import unicodedata

import pandas as pd
import requests

LEAGUES = {'E0':'England Premier League','E1':'England Championship','E2':'England League One',
'E3':'England League Two','SC0':'Scotland Premiership','D1':'Germany Bundesliga',
'D2':'Germany 2. Bundesliga','I1':'Italy Serie A','I2':'Italy Serie B',
'SP1':'Spain La Liga','SP2':'Spain Segunda','F1':'France Ligue 1','F2':'France Ligue 2',
'N1':'Netherlands Eredivisie','B1':'Belgium First Division','P1':'Portugal Primeira Liga'}
EXTRA = {'SWE':'Sweden Allsvenskan','NOR':'Norway Eliteserien','DNK':'Denmark Superliga',
'FIN':'Finland Veikkausliiga','AUT':'Austria Bundesliga','IRL':'Ireland Premier',
'SWZ':'Switzerland Super League','USA':'USA MLS','BRA':'Brazil Serie A',
'ARG':'Argentina Primera','POL':'Poland Ekstraklasa','JPN':'Japan J League'}

class PublicResearchError(RuntimeError): pass

ALIASES = {
 'ifk goteborg':'goteborg','ifk goteb':'goteborg','goteborg':'goteborg','ifk gothenburg':'goteborg',
 'bk hacken':'hacken','hacken':'hacken','elfsborg':'elfsborg','if elfsborg':'elfsborg',
 'orgryte':'orgryte','orgryte is':'orgryte','vasteras':'vasteras','vasteras sk':'vasteras',
 'brommapojkarna':'brommapojkarna','if brommapojkarna':'brommapojkarna','bp':'brommapojkarna',
 'athletic bilbao':'ath bilbao','athletic club':'ath bilbao','at bilbao':'ath bilbao',
 'real sociedad':'sociedad','r sociedad':'sociedad',
 'racing santander':'racing santander','racing sa':'racing santander',
 'real madrid':'real madrid','r madrid':'real madrid',
 'man utd':'man united','manchester utd':'man united',
 'inter milan':'inter','internazionale':'inter','ac milan':'milan',
 'paris saint germain':'paris sg','psg':'paris sg',
 'borussia dortmund':'dortmund','newcastle united':'newcastle',
 'tottenham hotspur':'tottenham','west ham united':'west ham',
}

def clean(name):
    s=unicodedata.normalize('NFKD',str(name).casefold())
    s=''.join(c for c in s if not unicodedata.combining(c))
    s=re.sub(r'[^a-z0-9 ]+',' ',s)
    s=re.sub(r'\s+',' ',s).strip()
    return ALIASES.get(s,s)

def seasons(date):
    year=date.year if date.month>=7 else date.year-1
    return [f'{y%100:02d}{(y+1)%100:02d}' for y in (year,year-1)]

def _parse_csv(content, source, now):
    df=pd.read_csv(BytesIO(content), encoding='cp1252', encoding_errors='replace', on_bad_lines='skip', low_memory=False)
    df.columns=[str(c).strip() for c in df.columns]
    # Extra-league files normally share the same column names, but accept common variants.
    aliases={'HomeTeam':['HomeTeam','Home','Home Team'], 'AwayTeam':['AwayTeam','Away','Away Team'],
             'FTHG':['FTHG','HG','HomeGoals'], 'FTAG':['FTAG','AG','AwayGoals'],
             'Date':['Date','MatchDate']}
    rename={}
    for canonical, variants in aliases.items():
        candidate=next((x for x in variants if x in df.columns),None)
        if candidate is None: raise ValueError(f'Missing column {canonical}: {list(df.columns)[:12]}')
        rename[candidate]=canonical
    df=df.rename(columns=rename)[['HomeTeam','AwayTeam','FTHG','FTAG','Date']].copy()
    df['Date']=pd.to_datetime(df['Date'],dayfirst=True,errors='coerce',format='mixed')
    for col in ('FTHG','FTAG'): df[col]=pd.to_numeric(df[col],errors='coerce')
    df=df.dropna(subset=['HomeTeam','AwayTeam','FTHG','FTAG','Date'])
    cutoff=pd.Timestamp(now.date())
    df=df[(df.Date<cutoff)&(df.Date>=cutoff-pd.Timedelta(days=850))]
    df['division']=source
    return df

def load_results(session=None,now=None,divisions=None):
    now=now or datetime.now(timezone.utc)
    client=session or requests.Session()
    data=[]; warnings=[]
    urls=[]
    for season in seasons(now):
        for division in (divisions if divisions is not None else LEAGUES):
            urls.append((division,f'https://www.football-data.co.uk/mmz4281/{season}/{division}.csv'))
    # Explicit divisions parameter preserves compatibility with existing tests.
    if divisions is None:
        urls += [(code,f'https://www.football-data.co.uk/new/{code}.csv') for code in EXTRA]
    for source,url in urls:
        try:
            response=client.get(url,timeout=9,headers={'User-Agent':'QuantPoolPro/1.0 (personal research)'})
            response.raise_for_status()
            df=_parse_csv(response.content,source,now)
            if not df.empty: data.append(df)
        except (requests.RequestException, ValueError, KeyError, UnicodeError, pd.errors.ParserError) as exc:
            warnings.append(f'{source}: {type(exc).__name__} ({str(exc)[:100]})')
    if not data: raise PublicResearchError('Inga matchresultat kunde hämtas från datakällorna')
    return pd.concat(data,ignore_index=True).drop_duplicates(subset=['Date','HomeTeam','AwayTeam','FTHG','FTAG']),warnings

def resolve(name,teams):
    key=clean(name)
    exact=sorted(x for x in teams if clean(x)==key)
    if len(exact)==1: return exact[0]
    if len(exact)>1: return None
    scores=sorted(((SequenceMatcher(None,key,clean(t)).ratio(),t) for t in teams),reverse=True)
    if scores and scores[0][0]>=0.94 and (len(scores)==1 or scores[0][0]-scores[1][0]>=0.14):
        return scores[0][1]
    return None

def analyze_match(home,away,results,limit=10):
    teams=set(results['HomeTeam']).union(results['AwayTeam'])
    h=resolve(home,teams); a=resolve(away,teams)
    result={'home':home,'away':away,'matched_home':h,'matched_away':a,
            'source':'football-data.co.uk','status':'unavailable',
            'injuries':'not verified','suspensions':'not verified','lineups':'not verified'}
    if not h or not a:
        missing=([f'hemmalag: {home}'] if not h else [])+([f'bortalag: {away}'] if not a else [])
        result['reason']='Ingen entydig lagmatchning för '+', '.join(missing)
        return result
    if h==a:
        result['reason']='Båda lag matchades till samma klubb';return result
    def form(team,venue=None):
        rows=results[(results.HomeTeam==team)|(results.AwayTeam==team)]
        if venue=='home': rows=rows[rows.HomeTeam==team]
        if venue=='away': rows=rows[rows.AwayTeam==team]
        rows=rows.sort_values('Date',ascending=False).head(limit)
        played=[]
        for _,r in rows.iterrows():
            at_home=r.HomeTeam==team
            gf=int(r.FTHG if at_home else r.FTAG);ga=int(r.FTAG if at_home else r.FTHG)
            played.append({'date':str(r.Date.date()),'opponent':r.AwayTeam if at_home else r.HomeTeam,
                           'result':'W' if gf>ga else 'D' if gf==ga else 'L','gf':gf,'ga':ga})
        n=len(played)
        return {'games':n,'points_per_game':round(sum(3 if x['result']=='W' else 1 if x['result']=='D' else 0 for x in played)/n,2) if n else None,
                'goals_for_per_game':round(sum(x['gf'] for x in played)/n,2) if n else None,
                'goals_against_per_game':round(sum(x['ga'] for x in played)/n,2) if n else None,'matches':played}
    h2h=results[((results.HomeTeam==h)&(results.AwayTeam==a))|((results.HomeTeam==a)&(results.AwayTeam==h))].sort_values('Date',ascending=False).head(5)
    result.update(status='ok',home_form=form(h),away_form=form(a),home_at_home=form(h,'home'),away_at_away=form(a,'away'),
                  h2h=[{'date':str(r.Date.date()),'home':r.HomeTeam,'away':r.AwayTeam,'score':f'{int(r.FTHG)}-{int(r.FTAG)}'} for _,r in h2h.iterrows()])
    return result
