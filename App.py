"""Quant Pool Engine 3.0: probabilistic pool coupon explorer (not a betting service)."""
import io
import heapq
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.optimize import brentq

SIGNS = ('1', 'X', '2')
PRODUCTS = {'Powerplay (8)': ('powerplay', 8), 'Stryktipset (13)': ('stryktipset', 13),
            'Topptipset (8)': ('topptipset', 8), 'Europatipset (13)': ('europatipset', 13)}
BASE = 'https://api.spela.svenskaspel.se/draw/1'


def number(value, low=None, high=None):
    try:
        v = float(str(value).replace(',', '.'))
        if not math.isfinite(v) or (low is not None and v < low) or (high is not None and v > high):
            return None
        return v
    except (TypeError, ValueError):
        return None


def vector_from_fields(obj, fields, low, high):
    if not isinstance(obj, dict):
        return None
    vals = [number(obj.get(k), low, high) for k in fields]
    if any(x is None for x in vals) or sum(vals) <= 0:
        return None
    return np.asarray(vals, dtype=float)


def normalize(a):
    a = np.asarray(a, dtype=float)
    if a.shape != (3,) or not np.all(np.isfinite(a)) or np.any(a < 0) or a.sum() <= 0:
        raise ValueError('Ogiltig sannolikhetsfördelning')
    return a / a.sum()


def outcome_key(item):
    v = str(item.get('outcome') or item.get('id') or '').strip().upper()
    return {'1': 0, 'ONE': 0, 'HOME': 0, 'X': 1, 'DRAW': 1, 'TIE': 1,
            '2': 2, 'TWO': 2, 'AWAY': 2}.get(v)


def metrics_vector(ev, field, minimum, maximum):
    bm = ev.get('betMetrics') or {}
    vals = (bm.get('values') or []) if isinstance(bm, dict) else []
    found = {}
    if not isinstance(vals, list):
        return None
    for item in vals:
        if not isinstance(item, dict):
            continue
        idx = outcome_key(item)
        if idx is None or idx in found:
            continue
        v = item.get(field)
        if isinstance(v, dict):
            v = v.get(field)
        n = number(v, minimum, maximum)
        if n is not None:
            found[idx] = n
    return np.asarray([found[i] for i in range(3)], dtype=float) if len(found) == 3 else None


def extract_odds(ev, extra):
    for source in (ev, extra):
        arr = vector_from_fields(source.get('odds'), ('one', 'x', 'two'), 1.000001, None)
        if arr is not None:
            return arr, 'Odds'
        arr = metrics_vector(source, 'odds', 1.000001, None)
        if arr is not None:
            return arr, 'betMetrics'
    return None, 'Saknas'


def extract_streck(ev, extra):
    for source in (ev, extra):
        arr = vector_from_fields(source.get('svenskaFolket'), ('one', 'x', 'two'), 0, 100)
        if arr is not None:
            return normalize(arr)
        arr = metrics_vector(source, 'distribution', 0, 100)
        if arr is not None:
            return normalize(arr)
    return None


def shin(odds):
    """Return probability and provenance. Shin falls back safely if root is absent."""
    q = 1 / np.asarray(odds, dtype=float)
    s = q.sum()
    basic = normalize(q)
    if s <= 1.000001:
        return basic, 'Normaliserade odds'

    def calc(z):
        return (np.sqrt(z*z + 4*(1-z)*q*q/s) - z) / (2*(1-z))

    try:
        f0, f1 = calc(0).sum()-1, calc(0.999999).sum()-1
        if f0 == 0:
            return normalize(calc(0)), 'Shin'
        if f0*f1 < 0:
            z = brentq(lambda t: calc(t).sum()-1, 0, 0.999999)
            p = calc(z)
            if np.all(p > 0):
                return normalize(p), 'Shin'
    except (ValueError, FloatingPointError, ZeroDivisionError):
        pass
    return basic, 'Normaliserade odds (Shin ej möjlig)'


def is_player_duel(ev):
    match = ev.get('match') or {}
    labels = [ev.get('eventTypeDescription'), ev.get('eventType'), match.get('matchType'), match.get('type')]
    return any(any(token in str(label).lower() for token in ('h2h', 'head-to-head', 'duell', 'player duel', 'spelarduell')) for label in labels if label)


def model_event(ev, extra):
    odds, source = extract_odds(ev, extra)
    folk = extract_streck(ev, extra)
    if odds is not None:
        probs, method = shin(odds)
        source = f'{method} / {source}'
    elif folk is not None:
        probs = folk.copy()
        source = 'Streckproxy – odds saknas'
    else:
        raise ValueError('Saknar både giltiga odds och streck')
    # Do not use unvalidated form/rank adjustments: market odds remain baseline.
    return {'nr': ev.get('eventNumber'), 'match': ev.get('eventDescription') or 'Okänd match',
            'p': probs, 's': folk, 'source': source,
            'duel': is_player_duel(ev), 'proxy': odds is None}


@st.cache_data(ttl=120, show_spinner=False)
def get_draws(product):
    session = requests.Session()
    session.headers.update({'User-Agent': 'QuantPoolEngine/2.0'})
    resp = session.get(f'{BASE}/{product}/draws', timeout=12)
    resp.raise_for_status()
    payload = resp.json()
    draws = payload.get('draws') or []
    if not isinstance(draws, list):
        raise ValueError('Oväntat API-svar för omgångar')
    output = []
    for draw in draws:
        if not isinstance(draw, dict):
            continue
        state = str(draw.get('drawState') or '').lower()
        if state and state not in ('open', 'active', '10'):
            continue
        number_id = draw.get('drawNumber')
        draw = dict(draw)
        draw['_extra_stats'] = {}
        if number_id is not None:
            try:
                sr = session.get(f'{BASE}/{product}/draws/{number_id}/statistics', timeout=6)
                if sr.ok:
                    data = sr.json()
                    draw['_extra_stats'] = data.get('statistics') or {}
            except (requests.RequestException, ValueError):
                pass
        output.append(draw)
    return output


def top_k_rows(p, k):
    """Exact K most probable outcomes for independent matches, via heap search."""
    p = np.asarray(p, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or np.any(p <= 0):
        raise ValueError('p måste vara en positiv N×3-matris')
    orders = np.argsort(-p, axis=1)
    sorted_p = np.take_along_axis(p, orders, axis=1)
    n = len(p)
    start = (0,)*n
    heap = [(-float(np.log(sorted_p[:, 0]).sum()), start)]
    visited = {start}
    rows = []
    while heap and len(rows) < k:
        neg_log, pos = heapq.heappop(heap)
        rows.append(tuple(int(orders[i, pos[i]]) for i in range(n)))
        for i in range(n):
            if pos[i] == 2:
                continue
            nxt = list(pos)
            nxt[i] += 1
            nxt = tuple(nxt)
            if nxt not in visited:
                visited.add(nxt)
                next_score = neg_log + math.log(sorted_p[i, pos[i]]) - math.log(sorted_p[i, nxt[i]])
                heapq.heappush(heap, (next_score, nxt))
    return rows


def generate_candidates(p, s, k, candidate_cap=25000):
    """Union of top-K lists under different popularity penalties."""
    if s is None:
        return top_k_rows(p, k), 'Enbart sannolikhet – streck saknas'
    n = len(p)
    per_pass = max(k, min(candidate_cap // 7, 6500))
    candidate = set()
    for weight in (0.0, 0.10, 0.20, 0.30, 0.40, 0.55, 0.70):
        # Tempered rarity, bounded to avoid near-zero popularity dominating.
        log_score = np.log(p) - weight*np.log(np.clip(s, 0.015, 1))
        pseudo = np.exp(log_score - log_score.max(axis=1, keepdims=True))
        pseudo /= pseudo.sum(axis=1, keepdims=True)
        candidate.update(top_k_rows(pseudo, per_pass))
    return sorted(candidate), 'Sannolikhet + försiktig streckvärdesbonus'


def optimize(p, s, budget, stake, balance=0.30):
    """Choose exact rows with a transparent probability floor for value strategies.

    balance=0 returns the mathematically highest-probability K rows.
    Other values retain at least (1-balance) of that baseline probability mass,
    then prefer less publicly popular rows among a bounded candidate set.
    No monetary expected value is claimed.
    """
    p = np.asarray(p, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) not in (8, 13):
        raise ValueError('Endast 8 eller 13 matcher stöds')
    if not np.all(np.isfinite(p)) or np.any(p <= 0) or not np.allclose(p.sum(axis=1), 1):
        raise ValueError('Ogiltiga sannolikheter')
    if s is not None:
        s = np.asarray(s, dtype=float)
        if s.shape != p.shape or not np.all(np.isfinite(s)) or np.any(s < 0) or not np.allclose(s.sum(axis=1), 1):
            raise ValueError('Ogiltiga streckandelar')
    if not math.isfinite(float(budget)) or not math.isfinite(float(stake)) or stake <= 0 or budget < stake:
        raise ValueError('Budgeten måste räcka till minst en rad')
    if not 0 <= balance <= 1:
        raise ValueError('Risknivå måste ligga mellan 0 och 1')
    k = min(int(budget // stake), 3**len(p))
    baseline = np.asarray(top_k_rows(p, k), dtype=np.int8)
    match_ix = np.arange(len(p))
    base_probs = np.prod(p[match_ix, baseline], axis=1)
    baseline_mass = float(base_probs.sum())
    if s is None or balance == 0:
        chosen = baseline
        method = 'Exakt topp-K efter sannolikhet' if balance == 0 else 'Exakt topp-K (streck saknas)'
        candidate_count = k
    else:
        candidates, _ = generate_candidates(p, s, k)
        idx = np.asarray(sorted(set(map(tuple, candidates)) | set(map(tuple, baseline))), dtype=np.int8)
        probs = np.prod(p[match_ix, idx], axis=1)
        public = np.prod(np.clip(s[match_ix, idx], 0.015, 1), axis=1)
        # A smooth popularity-adjusted ranking, then enforce a portfolio-wide
        # probability floor by mixing back highest-probability baseline rows.
        score = np.log(probs) - balance * np.log(public)
        chosen_indices = np.argsort(-score, kind='stable')[:k]
        chosen_set = set(map(tuple, idx[chosen_indices]))
        chosen_mass = sum(float(np.prod(p[match_ix, row])) for row in chosen_set)
        floor = (1 - balance) * baseline_mass
        if chosen_mass < floor - 1e-14:
            # Replace weakest selected non-baseline candidates with strongest
            # missing baseline rows until the probability floor is satisfied.
            base_set = set(map(tuple, baseline))
            removable = sorted((row for row in chosen_set if row not in base_set),
                               key=lambda row: float(np.prod(p[match_ix, row])))
            missing = [tuple(row) for row in baseline if tuple(row) not in chosen_set]
            for outgoing, incoming in zip(removable, missing):
                chosen_set.remove(outgoing)
                chosen_set.add(incoming)
                chosen_mass += float(np.prod(p[match_ix, incoming]) - np.prod(p[match_ix, outgoing]))
                if chosen_mass >= floor - 1e-14:
                    break
        chosen = np.asarray(sorted(chosen_set), dtype=np.int8)
        candidate_count = len(idx)
        method = f'Streckjusterad kandidatoptimering; minst {100*(1-balance):.0f} % av topp-K-träffchansen'
    selected_probs = np.prod(p[match_ix, chosen], axis=1)
    return {'rows': chosen, 'probabilities': selected_probs,
            'full_hit_chance': float(selected_probs.sum()), 'cost': k*stake,
            'method': method, 'candidate_count': candidate_count,
            'baseline_chance': baseline_mass,
            'is_global_optimum': bool(s is None or balance == 0)}


def assess_rows(rows, p, s=None):
    """Evaluate unique exact rows with the same model probabilities."""
    arr = np.asarray(rows, dtype=int)
    p = np.asarray(p, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != len(p) or len(arr) == 0:
        raise ValueError('Fel antal matcher eller tom radfil')
    if np.any((arr < 0) | (arr > 2)) or len(np.unique(arr, axis=0)) != len(arr):
        raise ValueError('Ogiltiga tecken eller dubbletter i radfilen')
    ix = np.arange(len(p))
    probs = np.prod(p[ix, arr], axis=1)
    out = {'rows': len(arr), 'chance': float(probs.sum()), 'probabilities': probs}
    if s is not None:
        public = np.prod(np.clip(np.asarray(s)[ix, arr], 1e-8, 1), axis=1)
        out['public_mass'] = float(public.sum())
        out['popularity_ratio'] = float(np.sum(probs / np.maximum(public, 1e-12)) / len(arr))
    return out


def parse_legacy_txt(content, expected_matches):
    """Read Svenska Spel style E,1,X,2 rows. Header is ignored."""
    content = content.decode('utf-8-sig') if isinstance(content, bytes) else content
    rows = []
    for line in content.splitlines():
        parts = [x.strip().upper() for x in line.split(',')]
        if not parts or parts[0] != 'E':
            continue
        signs = parts[1:]
        if len(signs) != expected_matches or any(x not in SIGNS for x in signs):
            raise ValueError('Felaktig E-rad i TXT-filen')
        rows.append([SIGNS.index(x) for x in signs])
    if not rows:
        raise ValueError('Inga E-rader hittades')
    arr = np.asarray(rows, dtype=np.int8)
    if len(np.unique(arr, axis=0)) != len(arr):
        raise ValueError('TXT-filen innehåller dubbletter')
    return arr


def strategy_comparison(p, s, budget, stake, balance=0.30):
    """A: exact probability; B: bounded compromise; C: value-oriented proxy."""
    return {
        'Högsta träffchans': optimize(p, s, budget, stake, 0),
        'Balanserad': optimize(p, s, budget, stake, balance),
        'Mer streckvärde': optimize(p, s, budget, stake, 0.65),
    }


def sign_distribution(rows):
    arr = np.asarray(rows, dtype=int)
    if arr.ndim != 2 or len(arr) == 0 or np.any((arr < 0) | (arr > 2)):
        raise ValueError('Ogiltiga rader')
    return np.stack([(arr == i).mean(axis=0) for i in range(3)], axis=1)


def rows_txt(rows, product, draw_number):
    arr = np.asarray(rows, dtype=int)
    if arr.ndim != 2 or arr.shape[1] not in (8, 13) or len(arr) == 0 or np.any((arr < 0) | (arr > 2)):
        raise ValueError('Ogiltiga rader för TXT-export')
    lines = [f'{product.capitalize()},Omg={draw_number}']
    lines.extend('E,' + ','.join(SIGNS[x] for x in row) for row in arr)
    return ('\r\n'.join(lines) + '\r\n').encode('utf-8')


def backtest_rounds(df, budget=300, stake=1, balance=0.30):
    """Evaluate historical snapshots (pre-match probabilities, streck and final outcomes).

    Expected CSV columns: draw, match, p1, px, p2, s1, sx, s2, result.
    Every draw must contain exactly 8 or 13 matches. Returns one record per
    draw/strategy. Does not estimate winnings without historical prize data.
    """
    needed = {'draw', 'match', 'p1', 'px', 'p2', 's1', 'sx', 's2', 'result'}
    if not needed.issubset(df.columns):
        raise ValueError('Historikfilen saknar kolumner: ' + ', '.join(sorted(needed-set(df.columns))))
    output = []
    for draw, part in df.groupby('draw', sort=False):
        part = part.sort_values('match')
        n = len(part)
        if n not in (8, 13) or part['match'].duplicated().any():
            raise ValueError(f'Omgång {draw}: måste ha 8 eller 13 unika matcher')
        p = part[['p1','px','p2']].to_numpy(dtype=float)
        s = part[['s1','sx','s2']].to_numpy(dtype=float)
        if not np.all(np.isfinite(p)) or np.any(p <= 0) or not np.allclose(p.sum(axis=1), 1):
            raise ValueError(f'Omgång {draw}: ogiltiga matchsannolikheter')
        if not np.all(np.isfinite(s)) or np.any(s < 0) or not np.allclose(s.sum(axis=1), 1):
            raise ValueError(f'Omgång {draw}: ogiltiga streck')
        results = part['result'].astype(str).str.upper().tolist()
        if any(x not in SIGNS for x in results):
            raise ValueError(f'Omgång {draw}: ogiltiga matchresultat')
        actual = np.array([SIGNS.index(x) for x in results])
        for name, ticket in strategy_comparison(p, s, budget, stake, balance).items():
            hits = (ticket['rows'] == actual).sum(axis=1)
            output.append({'Omgång': draw, 'Strategi': name, 'Rader': len(hits),
                           'Kostnad (kr)': ticket['cost'],
                           'Modellchans (%)': ticket['full_hit_chance']*100,
                           'Max rätt': int(hits.max()),
                           'Antal fullträffar': int(np.count_nonzero(hits == n))})
    return pd.DataFrame(output)


def rows_csv(rows):
    df = pd.DataFrame([[SIGNS[x] for x in row] for row in rows], columns=[f'M{i+1}' for i in range(rows.shape[1])])
    return df.to_csv(index=False, sep=';').encode('utf-8-sig')


def app():
    st.set_page_config(page_title='Quant Pool Engine 3.0', page_icon='🧠', layout='wide')
    st.title('🧠 Quant Pool Engine 3.0')
    st.caption('Automatisk kuponganalys för Powerplay och Stryktipset – med tydlig riskredovisning.')
    selected = st.sidebar.selectbox('Spelform', list(PRODUCTS))
    product, count = PRODUCTS[selected]
    budget = st.sidebar.number_input('Maxbudget (kr)', min_value=1, max_value=5000, value=150)
    stake = 1 if count == 13 else st.sidebar.selectbox('Radinsats (kr)', [1, 2, 5, 10])
    if count == 13:
        st.sidebar.caption('13-matchersspel: 1 kr per rad enligt befintlig app. Kontrollera aktuella villkor.')
    balance = st.sidebar.slider('B: tillåten förlust av träffchans (%)', 0, 70, 30, 5) / 100
    st.sidebar.caption('B garanteras minst 100 minus valt procenttal av A:s modellerade träffchans. C använder 65 % gräns. Ingen avkastningsprognos.')
    if st.sidebar.button('🔄 Uppdatera API-data'):
        get_draws.clear()
        st.rerun()
    try:
        draws = get_draws(product)
    except (requests.RequestException, ValueError) as exc:
        st.error(f'Kunde inte hämta omgångar: {exc}')
        st.stop()
    if not draws:
        st.warning('Inga tillgängliga omgångar hittades. API-schemat eller status kan ha ändrats.')
        st.stop()
    draw = st.selectbox('Välj omgång', draws, format_func=lambda d: f"Omgång {d.get('drawNumber')} – {d.get('drawComment', '')}")
    close_str = draw.get('regCloseTime')
    if close_str:
        try:
            close_dt = datetime.fromisoformat(close_str.replace('Z', '+00:00'))
            if close_dt.tzinfo and close_dt < datetime.now(timezone.utc):
                st.error('Spelstopp har passerat. Kupongen visas endast för analys.')
        except ValueError:
            st.warning('Kunde inte tolka spelstoppstiden.')
    events = draw.get('drawEvents') or []
    if len(events) != count:
        st.error(f'Förväntade {count} matcher, fick {len(events)}. Ingen kupong skapas.')
        st.stop()
    extra = draw.get('_extra_stats') or {}
    extras = (extra.get('events') or extra.get('drawEvents') or []) if isinstance(extra, dict) else []
    extra_map = {str(x.get('eventNumber')): x for x in extras if isinstance(x, dict)}
    matches = []
    for i, ev in enumerate(events):
        try:
            matches.append(model_event(ev, extra_map.get(str(ev.get('eventNumber')), {})))
        except (ValueError, AttributeError) as exc:
            st.error(f'Match {i+1}: {exc}. Ingen kupong skapas.')
            st.stop()
    p = np.array([m['p'] for m in matches])
    s = np.array([m['s'] for m in matches]) if all(m['s'] is not None for m in matches) else None
    if s is None:
        st.warning('Minst en match saknar streckfördelning. Endast sannolikhet används.')
    if any(m['proxy'] for m in matches):
        st.warning('Minst en match saknar odds och använder folkets streck som osäker sannolikhetsproxy.')
    if s is not None:
        st.info('Streckvärde är en indikator, inte en beräkning av verklig utdelning eller positiv förväntad avkastning.')
    result = optimize(p, s, budget, stake, balance)
    a, b, c = st.columns(3)
    a.metric('Kupongkostnad', f"{result['cost']} kr")
    b.metric('Modellchans till alla rätt', f"{result['full_hit_chance']:.3%}")
    c.metric('Antal rader', f"{len(result['rows']):,}".replace(',', ' '))
    st.caption('Chansen förutsätter oberoende matcher och korrekta sannolikheter. Historisk kalibrering saknas.')
    st.caption('Nyckeltalen ovan avser strategi B. Strategi A är ett exakt topp-K-optimum enligt matchmodellen.')
    st.subheader('Strategijämförelse')
    strategies = strategy_comparison(p, s, budget, stake, balance)
    comparison = []
    for name, strategy in strategies.items():
        evaluation = assess_rows(strategy['rows'], p, s)
        comparison.append({'Strategi': name, 'Rader': evaluation['rows'],
                           'Kostnad (kr)': strategy['cost'],
                           'Modellchans alla rätt (%)': round(evaluation['chance']*100, 5),
                           'Folkets täckta sannolikhetsmassa (%)': round(evaluation.get('public_mass', float('nan'))*100, 5)})
    st.dataframe(pd.DataFrame(comparison), use_container_width=True, hide_index=True)
    st.caption('Folkets sannolikhetsmassa är ett mått på popularitet, INTE förväntad utdelning eller ROI. '
               'Träffchans bygger på samma modell för alla strategier.')
    choice = st.selectbox('Visa och exportera strategi', list(strategies), index=1)
    result = strategies[choice]
    old_upload = st.file_uploader('Jämför med äldre Svenska Spel-radfil (.txt)', type=['txt'])
    if old_upload is not None:
        try:
            old_rows = parse_legacy_txt(old_upload.getvalue(), count)
            old_eval = assess_rows(old_rows, p, s)
            new_eval = assess_rows(result['rows'], p, s)
            overlap = len(set(map(tuple, old_rows)) & set(map(tuple, result['rows'])))
            st.write({'Gammal fil – antal rader': len(old_rows),
                      'Gammal fil – modellchans (%)': round(old_eval['chance']*100, 5),
                      'Vald strategi – modellchans (%)': round(new_eval['chance']*100, 5),
                      'Gemensamma rader': overlap})
            if len(old_rows)*stake != result['cost']:
                st.warning('Olika kostnad: jämförelsen är inte budgetneutral.')
        except (ValueError, UnicodeError) as exc:
            st.error(f'Kunde inte läsa gamla kupongen: {exc}')
    st.download_button('⬇️ Exportera vald strategi som CSV', rows_csv(result['rows']),
                       file_name=f"{product}_{draw.get('drawNumber')}_{choice.replace(' ', '_')}.csv",
                       mime='text/csv')
    st.download_button('⬇️ Exportera E-rader som TXT (ej verifierat inlämningsformat)',
                       rows_txt(result['rows'], product, draw.get('drawNumber')),
                       file_name=f"{product}_{draw.get('drawNumber')}_rader.txt", mime='text/plain')
    st.subheader('Teckenfördelning på valda rader')
    allocation = sign_distribution(result['rows'])
    st.dataframe(pd.DataFrame({'Match': np.arange(1, count+1),
                               '1 (%)': np.round(allocation[:, 0]*100, 1),
                               'X (%)': np.round(allocation[:, 1]*100, 1),
                               '2 (%)': np.round(allocation[:, 2]*100, 1)}),
                 use_container_width=True, hide_index=True)
    st.caption('Teckenfördelningen beskriver de spelade raderna, inte sannolikheten för respektive match.')
    st.subheader('Matchanalys')
    table = []
    for i, m in enumerate(matches):
        used = set(int(x) for x in result['rows'][:, i])
        table.append({'Nr': m['nr'] or i+1, 'Match': m['match'],
                      'Valda tecken': ''.join(SIGNS[j] for j in range(3) if j in used),
                      'Typ': ('Spik' if len(used)==1 else 'Halv' if len(used)==2 else 'Hel'),
                      'P(1) %': round(100*m['p'][0], 1), 'P(X) %': round(100*m['p'][1], 1),
                      'P(2) %': round(100*m['p'][2], 1),
                      'Streck 1 %': round(100*m['s'][0], 1) if m['s'] is not None else None,
                      'Streck X %': round(100*m['s'][1], 1) if m['s'] is not None else None,
                      'Streck 2 %': round(100*m['s'][2], 1) if m['s'] is not None else None,
                      'Datakälla': m['source']})
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.subheader('Valda rader')
    row_df = pd.DataFrame([[SIGNS[x] for x in row] for row in result['rows']],
                          columns=[f'M{i+1}' for i in range(count)])
    row_df.insert(0, 'Rad', np.arange(1, len(row_df)+1))
    row_df['Modellchans %'] = np.round(result['probabilities']*100, 6)
    st.dataframe(row_df, use_container_width=True, hide_index=True, height=360)
    st.download_button('⬇️ Ladda ned rader som CSV', rows_csv(result['rows']),
                       file_name=f"{product}_{draw.get('drawNumber')}_rader.csv", mime='text/csv')
    with st.expander('Historisk testning – importera egna omgångar'):
        st.caption('Ladda upp CSV med kolumner: draw, match, p1, px, p2, s1, sx, s2, result. '
                   'Sannolikheter och streck måste vara sparade före matchstart, inte hämtade i efterhand.')
        history_upload = st.file_uploader('Historiska omgångar (CSV)', type=['csv'], key='history')
        if history_upload is not None:
            try:
                history = pd.read_csv(history_upload, sep=None, engine='python')
                history_result = backtest_rounds(history, budget, stake, balance)
                st.dataframe(history_result, use_container_width=True, hide_index=True)
                st.download_button('Ladda ned backtestresultat', history_result.to_csv(index=False).encode('utf-8-sig'),
                                   file_name='quant_pool_backtest.csv', mime='text/csv')
            except (ValueError, pd.errors.ParserError, UnicodeError) as exc:
                st.error(f'Historikfilen kunde inte analyseras: {exc}')
    with st.expander('Metod, begränsningar och datakvalitet'):
        st.write(f"Metod: {result['method']}. Kandidatrader: {result['candidate_count']}.")
        st.write('A är exakt topp-K enligt antagandet om oberoende matcher. B och C använder kandidatbaserad heuristik med sannolikhetsgolv; ingen garanti om högsta utdelning.')
        st.write('CSV är en analysfil, inte ett verifierat uppladdningsformat hos Svenska Spel.')
        st.write('Ingen automatisk insats, kontoinloggning eller spelinlämning utförs.')
        st.write('För ekonomiska slutsatser krävs historiska odds, streck, verkliga utdelningar och backtesting.')


if __name__ == '__main__':
    app()
