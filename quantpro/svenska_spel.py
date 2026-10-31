"""Best-effort public Svenska Spel draw reader. Fails closed on unknown schema."""
from datetime import datetime, timezone
import requests

BASE = 'https://api.spela.svenskaspel.se/draw/1'
PRODUCTS = {'Stryktipset': 'stryktipset', 'Europatipset': 'europatipset', 'Topptipset': 'topptipset'}

class FeedError(RuntimeError):
    pass

def _objects(data):
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _objects(v)
    elif isinstance(data, list):
        for v in data:
            yield from _objects(v)

def _participants(event):
    ps = event.get('participants')
    if not isinstance(ps, list):
        return None
    home = next((p.get('name') for p in ps if isinstance(p, dict) and p.get('type') == 'home'), None)
    away = next((p.get('name') for p in ps if isinstance(p, dict) and p.get('type') == 'away'), None)
    return (home, away) if home and away else None

def parse_draw(data, product):
    """Read recognizable fixtures; odds/streck only when explicitly mapped and valid."""
    required = 8 if product == 'topptipset' else 13
    candidates = []
    for obj in _objects(data):
        teams = _participants(obj)
        if teams:
            candidates.append({'home': teams[0], 'away': teams[1], 'raw': obj})
    # Avoid silently showing a partial or duplicate coupon.
    unique = []
    seen = set()
    for match in candidates:
        key = (match['home'], match['away'])
        if key not in seen:
            seen.add(key)
            unique.append(match)
    if len(unique) != required:
        raise FeedError(f'API-formatet kunde inte verifieras: hittade {len(unique)} unika matcher, väntade {required}. Visar inga osäkra data.')
    return [{'Nr': i + 1, 'Hemma': m['home'], 'Borta': m['away']} for i, m in enumerate(unique)]

def fetch_coupon(product, draw_number, session=None):
    if product not in PRODUCTS.values():
        raise ValueError('Okänd speltyp')
    draw_number = int(draw_number)
    if draw_number <= 0:
        raise ValueError('Ogiltigt omgångsnummer')
    client = session or requests
    url = f'{BASE}/{product}/draws/{draw_number}'
    try:
        response = client.get(url, timeout=15, headers={'Accept': 'application/json', 'User-Agent': 'QuantPoolPro/0.2'})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FeedError(f'Kunde inte hämta JSON från Svenska Spel: {exc}') from exc
    return {'source': url, 'fetched_utc': datetime.now(timezone.utc).isoformat(), 'matches': parse_draw(data, product)}
