"""Transparent market model and pool portfolio tools. No claimed guaranteed profit."""
import heapq
import math
from collections import Counter

SIGNS = ('1', 'X', '2')

def probabilities(odds):
    if odds is None or len(odds) != 3 or any(not math.isfinite(float(x)) or float(x) <= 1 for x in odds):
        raise ValueError('Tre giltiga decimalodds krävs')
    inv = [1/float(x) for x in odds]
    return [v/sum(inv) for v in inv]

def value_table(match):
    odds, streck = match.get('odds'), match.get('streck')
    if not odds: return []
    p = probabilities(odds)
    return [{'Tecken': sign, 'Odds': odds[i], 'Marknad %': round(100*p[i], 1),
             'Streck %': round(100*streck[i], 1) if streck else None,
             'Skillnad pp': round(100*(p[i]-streck[i]), 1) if streck else None}
            for i, sign in enumerate(SIGNS)]

def top_rows(matches, count):
    if count < 1 or count > 10000: raise ValueError('Antal rader måste vara 1–10000')
    p = [probabilities(m['odds']) for m in matches]
    if len(p) not in (8, 13): raise ValueError('Kräver 8 eller 13 matcher')
    order = [sorted(range(3), key=lambda i: -prob[i]) for prob in p]
    initial = (0,) * len(p)
    def score(state): return sum(math.log(p[i][order[i][state[i]]]) for i in range(len(p)))
    heap = [(-score(initial), initial)]
    visited = {initial}
    out = []
    while heap and len(out) < count:
        _, state = heapq.heappop(heap)
        out.append(''.join(SIGNS[order[i][state[i]]] for i in range(len(p))))
        for i in range(len(p)):
            if state[i] == 2: continue
            new = list(state); new[i] += 1; new = tuple(new)
            if new not in visited:
                visited.add(new); heapq.heappush(heap, (-score(new), new))
    return out

def summarize(rows, matches):
    n = len(matches)
    if not rows or any(len(row) != n or any(c not in SIGNS for c in row) for row in rows):
        raise ValueError('Ogiltiga rader')
    if len(set(rows)) != len(rows): raise ValueError('Dubblettrader')
    dist = [{sign: round(100*sum(r[i] == sign for r in rows)/len(rows), 1) for sign in SIGNS} for i in range(n)]
    p = [probabilities(m['odds']) for m in matches]
    mass = sum(math.prod(p[i][SIGNS.index(sign)] for i, sign in enumerate(row)) for row in rows)
    return {'rows': len(rows), 'chance_13_or_8': mass, 'distribution': dist}

def score_rows(rows, results):
    if any(x not in (*SIGNS, '?') for x in results): raise ValueError('Ogiltiga resultat')
    known = sum(x != '?' for x in results)
    counts = Counter(sum(a == b for a, b in zip(row, results) if b != '?') for row in rows)
    return {'known': known, 'distribution': dict(sorted(counts.items())),
            'max_possible': max(counts, default=0) + len(results)-known}

def export_txt(rows, product, number):
    slug = {'Stryktipset':'Stryktipset','Europatipset':'Europatipset',
            'Topptipset':'Topptipset','Powerplay':'Powerplay'}[product]
    return ('\r\n'.join([f'{slug},Omg={number}'] + ['E,'+','.join(r) for r in rows])+'\r\n').encode('utf-8')
