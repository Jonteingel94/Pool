"""Svenska Spel adapter: no synthetic live data, explicit provenance."""
from datetime import datetime, timezone
import math
import requests

BASE = 'https://api.spela.svenskaspel.se/draw/1'
PRODUCTS = {'Stryktipset': ('stryktipset', 13), 'Europatipset': ('europatipset', 13),
            'Topptipset': ('topptipset', 8), 'Powerplay': ('powerplay', 8)}

class FeedError(RuntimeError):
    pass

def _num(v, low=0, high=float('inf')):
    try:
        n = float(str(v).replace(',', '.'))
        return n if math.isfinite(n) and low <= n <= high else None
    except (TypeError, ValueError):
        return None

def _vector(obj, keys, lo, hi):
    if not isinstance(obj, dict):
        return None
    v = [_num(obj.get(k), lo, hi) for k in keys]
    return v if all(x is not None for x in v) and sum(v) > 0 else None

def _metrics(ev, field, lo, hi):
    bm = ev.get('betMetrics') or {}
    vals = bm.get('values', []) if isinstance(bm, dict) else []
    if not isinstance(vals, list):
        return None
    lookup = {'1': 0, 'ONE': 0, 'HOME': 0, 'X': 1, 'DRAW': 1, 'TIE': 1,
              '2': 2, 'TWO': 2, 'AWAY': 2}
    found = {}
    for item in vals:
        if not isinstance(item, dict):
            continue
        idx = lookup.get(str(item.get('outcome') or item.get('id') or '').upper())
        value = item.get(field)
        if isinstance(value, dict):
            value = value.get(field)
        n = _num(value, lo, hi)
        if idx is not None and n is not None and idx not in found:
            found[idx] = n
    return [found[i] for i in range(3)] if len(found) == 3 else None

def _prob(v):
    if v is None or sum(v) <= 0:
        return None
    return [x / sum(v) for x in v]

def _teams(ev):
    participants = ev.get('participants')
    if isinstance(participants, list):
        home = next((p.get('name') for p in participants if isinstance(p, dict) and str(p.get('type')).lower() == 'home'), None)
        away = next((p.get('name') for p in participants if isinstance(p, dict) and str(p.get('type')).lower() == 'away'), None)
        if home and away:
            return str(home), str(away)
    match = ev.get('match') or {}
    if isinstance(match, dict):
        h, a = match.get('homeTeam'), match.get('awayTeam')
        if isinstance(h, dict): h = h.get('name')
        if isinstance(a, dict): a = a.get('name')
        if h and a: return str(h), str(a)
    desc = ev.get('eventDescription')
    if isinstance(desc, str):
        for sep in (' - ', ' – ', ' — '):
            if sep in desc:
                h, a = desc.split(sep, 1)
                if h.strip() and a.strip(): return h.strip(), a.strip()
    return None

def _extract(ev, extra):
    odds = None
    streck = None
    for src in (ev, extra):
        if not isinstance(src, dict): continue
        if odds is None:
            odds = _vector(src.get('odds'), ('one', 'x', 'two'), 1.000001, 10000) or _metrics(src, 'odds', 1.000001, 10000)
        if streck is None:
            streck = _vector(src.get('svenskaFolket'), ('one', 'x', 'two'), 0, 100) or _metrics(src, 'distribution', 0, 100)
    return odds, _prob(streck)

def parse_draw(payload, product):
    if product not in PRODUCTS: raise FeedError('Okänd speltyp')
    _, expected = PRODUCTS[product]
    draw = payload.get('draw') if isinstance(payload, dict) and isinstance(payload.get('draw'), dict) else payload
    if not isinstance(draw, dict): raise FeedError('Oväntat API-format')
    events = draw.get('events')
    if not isinstance(events, list):
        # Some draw responses nest events under a coupon/round object.
        def walk(obj):
            if isinstance(obj, dict):
                if _teams(obj):
                    yield obj
                else:
                    for value in obj.values():
                        yield from walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    yield from walk(value)
        events = list(walk(draw))
    if not events:
        raise FeedError('Kunde inte hitta matcher i API-svaret')
    extra = draw.get('statistics') or {}
    rows = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict): continue
        teams = _teams(ev)
        if not teams: raise FeedError(f'Saknar lag för match {i+1}; visar inte en osäker kupong')
        number = ev.get('eventNumber')
        try: number = int(number) if number is not None else i+1
        except (ValueError, TypeError): raise FeedError('Ogiltigt matchnummer')
        stat = extra.get(str(number), extra.get(number, {})) if isinstance(extra, dict) else {}
        odds, streck = _extract(ev, stat)
        rows.append({'Nr': number, 'Hemma': teams[0], 'Borta': teams[1], 'odds': odds, 'streck': streck})
    rows.sort(key=lambda x: x['Nr'])
    if len(rows) != expected or [r['Nr'] for r in rows] != list(range(1, expected+1)):
        raise FeedError(f'Kupongen innehåller inte {expected} entydiga matcher')
    return rows

def fetch_draw(product, number, session=None, include_statistics=True):
    if product not in PRODUCTS: raise ValueError('Okänd speltyp')
    slug, _ = PRODUCTS[product]
    number = int(number)
    if number <= 0: raise ValueError('Omgång måste vara positiv')
    url = f'{BASE}/{slug}/draws/{number}'
    client = session or requests.Session()
    try:
        response = client.get(url, timeout=15, headers={'Accept': 'application/json'})
        response.raise_for_status()
        data = response.json()
        if include_statistics:
            try:
                sr = client.get(url+'/statistics', timeout=10, headers={'Accept': 'application/json'})
                if sr.ok:
                    stats = sr.json()
                    if isinstance(data, dict) and isinstance(stats, dict):
                        root = data.get('draw') if isinstance(data.get('draw'), dict) else data
                        root['statistics'] = stats.get('statistics') or stats
            except (requests.RequestException, ValueError):
                pass
    except (requests.RequestException, ValueError) as exc:
        raise FeedError(f'Kunde inte hämta Svenska Spel: {exc}') from exc
    return {'product': product, 'number': number, 'url': url,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'matches': parse_draw(data, product)}

def list_draws(product, session=None):
    if product not in PRODUCTS: raise ValueError('Okänd speltyp')
    slug, _ = PRODUCTS[product]
    client = session or requests.Session()
    try:
        response = client.get(f'{BASE}/{slug}/draws', timeout=15, headers={'Accept': 'application/json'})
        response.raise_for_status()
        data = response.json()
        draws = data.get('draws', [])
        return sorted({int(x['drawNumber']) for x in draws if isinstance(x, dict) and _num(x.get('drawNumber'), 1) is not None}, reverse=True)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        raise FeedError(f'Kunde inte lista omgångar: {exc}') from exc
