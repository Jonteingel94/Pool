"""Transparent 1X2 pricing and pool analysis. No fabricated live data."""
from dataclasses import dataclass
import math

OUTCOMES = ('1', 'X', '2')


def normalize(values):
    values = [float(v) for v in values]
    if len(values) != 3 or any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Ange tre positiva, ändliga värden')
    total = sum(values)
    return tuple(v / total for v in values)


def probabilities_from_odds(odds):
    """Remove bookmaker overround by proportional normalization."""
    odds = [float(x) for x in odds]
    if len(odds) != 3 or any(not math.isfinite(x) or x <= 1 for x in odds):
        raise ValueError('Odds måste vara större än 1')
    return normalize([1 / x for x in odds])


def analyze_match(odds, public_percent=None, model_probs=None):
    market = probabilities_from_odds(odds)
    model = normalize(model_probs) if model_probs is not None else market
    public = normalize(public_percent) if public_percent is not None else None
    rows = []
    for i, sign in enumerate(OUTCOMES):
        rows.append({
            'Tecken': sign,
            'Marknad %': round(100 * market[i], 2),
            'Modell %': round(100 * model[i], 2),
            'Streck %': round(100 * public[i], 2) if public else None,
            'Streckvärde (procentenheter)': round(100 * (model[i] - public[i]), 2) if public else None,
            'EV per krona': round(model[i] * float(odds[i]) - 1, 4),
        })
    return rows


def score_rows(rows, results):
    """Score complete 1X2 rows against known results; unknown results are None."""
    if len(results) not in (8, 13):
        raise ValueError('Resultat måste ha 8 eller 13 matcher')
    if any(r not in OUTCOMES and r is not None for r in results):
        raise ValueError('Ogiltigt matchresultat')
    scores = []
    for row in rows:
        if len(row) != len(results) or any(s not in OUTCOMES for s in row):
            raise ValueError('Ogiltig rad')
        known = sum(a == b for a, b in zip(row, results) if b is not None)
        remaining = sum(b is None for b in results)
        scores.append({'rätt_nu': known, 'max_rätt': known + remaining})
    return scores
