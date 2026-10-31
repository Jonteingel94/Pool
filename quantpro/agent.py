"""Transparent research-assisted forecasts; no claim of autonomous AI judgement.
Market baseline + bounded form adjustment (experimental, not calibrated).
"""
import math
from .pro_analysis import probabilities

SIGNS=('1','X','2')

def forecast(match, report=None, adjustment=0.0):
    odds=match.get('odds')
    if not odds: raise ValueError('Odds saknas')
    market=probabilities(odds)
    model=market[:]
    notes=['Baslinje: normaliserade marknadsodds (inte oberoende prognos).']
    if report and adjustment:
        teams=report.get('teams',{})
        h=teams.get(match['Hemma']); a=teams.get(match['Borta'])
        if h and a:
            delta=max(-0.08,min(0.08,(h['points_per_game']-a['points_per_game'])*adjustment))
            model=[market[0]+delta,market[1],market[2]-delta]
            if min(model)<=0: raise ValueError('Justeringen gav ogiltiga sannolikheter')
            total=sum(model);model=[x/total for x in model]
            notes.append('Experimentell formjustering; ej backtestad eller kalibrerad.')
        else: notes.append('Formdata saknas: ingen justering gjord.')
    s=match.get('streck')
    return {'market':market,'model':model,'streck':s,'difference_pp':
            [round((p-s[i])*100,2) for i,p in enumerate(model)] if s else None,
            'notes':notes}

def evaluate_brier(forecasts, outcomes):
    if len(forecasts)!=len(outcomes) or not forecasts: raise ValueError('Lika långa icke-tomma listor krävs')
    values=[]
    for p,o in zip(forecasts,outcomes):
        if o not in SIGNS or len(p)!=3 or any(not math.isfinite(x) or x<0 or x>1 for x in p) or abs(sum(p)-1)>1e-6:
            raise ValueError('Ogiltig prognos eller resultat')
        values.append(sum((p[i]-(1 if SIGNS[i]==o else 0))**2 for i in range(3)))
    return sum(values)/len(values)
