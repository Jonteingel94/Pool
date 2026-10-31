"""Opt-in API-Football research with explicit provenance and missing-data handling.
Uses API-Sports v3. No unsupported inferred lineup or injury claims.
"""
import re
import requests
from datetime import datetime, timezone

BASE='https://v3.football.api-sports.io'

class ResearchError(RuntimeError): pass

def normalized(s):
    return re.sub(r'[^a-z0-9]+','',str(s).lower().replace('å','a').replace('ä','a').replace('ö','o'))

class FootballResearch:
    def __init__(self, api_key, session=None):
        if not api_key: raise ResearchError('API_FOOTBALL_KEY saknas')
        self.key=api_key
        self.session=session or requests.Session()

    def get(self, path, params):
        try:
            r=self.session.get(BASE+path,params=params,headers={'x-apisports-key':self.key},timeout=18)
            r.raise_for_status()
            data=r.json()
        except (requests.RequestException, ValueError) as exc:
            raise ResearchError(str(exc)) from exc
        if not isinstance(data,dict) or not isinstance(data.get('response'),list):
            raise ResearchError('Oväntat API-Football-svar')
        if data.get('errors'):
            raise ResearchError(f"API-fel: {data['errors']}")
        return data['response']

    def find_team(self, name):
        teams=self.get('/teams',{'search':name})
        target=normalized(name)
        exact=[x for x in teams if normalized(x.get('team',{}).get('name',''))==target]
        if len(exact)!=1:
            raise ResearchError(f'Lagidentifiering osäker för {name!r}: {len(exact)} exakta träffar. Ange korrekt namn i API-Football.')
        return exact[0]['team']['id']

    def recent(self, team_id, last=10):
        fixtures=self.get('/fixtures',{'team':team_id,'last':last,'status':'FT'})
        matches=[]
        for item in fixtures:
            goals=item.get('goals') or {}; teams=item.get('teams') or {}; fixture=item.get('fixture') or {}
            h,a=teams.get('home') or {},teams.get('away') or {}
            if goals.get('home') is None or goals.get('away') is None: continue
            home=h.get('id')==team_id; away=a.get('id')==team_id
            if not (home or away): continue
            gf=goals['home'] if home else goals['away']; ga=goals['away'] if home else goals['home']
            matches.append({'date':fixture.get('date'),'opponent':a.get('name') if home else h.get('name'),
                            'home':home,'gf':gf,'ga':ga,'points':3 if gf>ga else 1 if gf==ga else 0})
        return matches

    def report(self, home, away):
        captured=datetime.now(timezone.utc).isoformat()
        report={'captured_at':captured,'source':'API-Football / API-Sports v3',
                'home':home,'away':away,'teams':{},'warnings':[]}
        for name in (home,away):
            try:
                tid=self.find_team(name)
                matches=self.recent(tid)
                if not matches: raise ResearchError('Ingen verifierad avslutad matchhistorik')
                report['teams'][name]={'team_id':tid,'matches':matches,
                    'points_per_game':round(sum(x['points'] for x in matches)/len(matches),3),
                    'goals_for_per_game':round(sum(x['gf'] for x in matches)/len(matches),3),
                    'goals_against_per_game':round(sum(x['ga'] for x in matches)/len(matches),3)}
            except ResearchError as exc:
                report['warnings'].append(f'{name}: {exc}')
        report['warnings'].append('Skador, xG och förväntade startelvor ingår inte i denna datakoppling; inga antaganden görs.')
        return report
