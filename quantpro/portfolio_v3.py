"""Diversified portfolio generator; experimental value-weighted mode.
Uses market odds and optional pool shares. Does not claim positive EV.
"""
import math
import random
from collections import Counter
from .pro_analysis import probabilities, SIGNS


def _weights(match, mode):
    p = probabilities(match['odds'])
    s = match.get('streck')
    if mode == 'value' and s and len(s) == 3:
        try:
            shares = [float(x) for x in s]
            if all(math.isfinite(x) and x >= 0 for x in shares) and abs(sum(shares)-1) < .05:
                # Mildly favor positive edges, retaining market probabilities.
                edge = [max(-.20, min(.20, p[i]-shares[i])) for i in range(3)]
                adjusted = [max(.01, p[i] * math.exp(2.5 * edge[i])) for i in range(3)]
                z = sum(adjusted)
                return [x/z for x in adjusted]
        except (ValueError, TypeError):
            pass
    return p


def _quotas(weights, n, max_share):
    # Largest-remainder allocation with upper bound per outcome.
    cap = math.ceil(n * max_share)
    if cap * 3 < n:
        raise ValueError('Maxandelen är för låg för tre tecken')
    counts = [0, 0, 0]
    for _ in range(n):
        available = [i for i in range(3) if counts[i] < cap]
        # Deficit to ideal allocation; picks the most underrepresented outcome.
        i = max(available, key=lambda j: (weights[j]*n-counts[j], weights[j], -j))
        counts[i] += 1
    return counts


def diversified_rows(matches, count, mode='balanced', max_share=.75, seed=2026):
    if not isinstance(count, int) or not 1 <= count <= 10000:
        raise ValueError('Antal rader måste vara 1–10000')
    if len(matches) not in (8, 13):
        raise ValueError('Kräver 8 eller 13 matcher')
    if mode not in ('balanced','value'):
        raise ValueError('Ogiltig strategi')
    if not .34 <= max_share <= 1:
        raise ValueError('Maxandelen måste vara mellan 34 och 100 procent')
    rng = random.Random(seed)
    quotas = [_quotas(_weights(m,mode),count,max_share) for m in matches]
    # Shuffle each match's exact sign quotas independently. Retry duplicates.
    # Duplicates are repaired with sign swaps that preserve the quotas.
    columns=[]
    for q in quotas:
        col=[SIGNS[i] for i in range(3) for _ in range(q[i])]
        rng.shuffle(col)
        columns.append(col)
    rows=[''.join(columns[j][i] for j in range(len(matches))) for i in range(count)]
    if len(set(rows)) != count:
        for _ in range(8):
            duplicates=[i for i,r in enumerate(rows) if rows.index(r)!=i]
            if not duplicates: break
            for i in duplicates:
                j=rng.randrange(len(matches)); k=rng.randrange(count)
                columns[j][i],columns[j][k]=columns[j][k],columns[j][i]
            rows=[''.join(columns[j][i] for j in range(len(matches))) for i in range(count)]
    if len(set(rows)) != count:
        raise ValueError('Kunde inte skapa unika rader med valda begränsningar. Prova annan budget/maxandel.')
    return rows


def distribution_warnings(rows):
    if not rows: return []
    warnings=[]
    for i in range(len(rows[0])):
        counts=Counter(r[i] for r in rows)
        if len(counts)==1:
            warnings.append(f'Match {i+1} är spikad till {next(iter(counts))}.')
        elif max(counts.values())/len(rows)>.90:
            warnings.append(f'Match {i+1}: över 90 % av raderna har samma tecken.')
    return warnings
