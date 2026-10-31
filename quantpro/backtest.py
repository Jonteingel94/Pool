"""Strict pre-match snapshot scoring. No leakage from post-match snapshots."""
from datetime import datetime
from .agent import evaluate_brier

def score_history(forecast_records, outcome_records):
    outcomes={(r['product'],r['draw']):r for r in outcome_records}
    data=[]
    for f in forecast_records:
        payload=f['payload']; key=(payload.get('product'),payload.get('draw'))
        result=outcomes.get(key)
        if not result: continue
        captured=datetime.fromisoformat(payload['captured_at'])
        cutoff=datetime.fromisoformat(payload['cutoff_at'])
        if captured>=cutoff: continue
        signs=result['payload'].get('results',[])
        predictions=payload.get('probabilities',[])
        if len(signs)!=len(predictions) or any(x not in ('1','X','2') for x in signs): continue
        data.append({'product':key[0],'draw':key[1],'brier':evaluate_brier(predictions,signs),'matches':len(signs)})
    return data
