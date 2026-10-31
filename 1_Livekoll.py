"""Livekoll for Svenska Spel TXT systems. Never treats missing results as a loss."""
import re
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
import streamlit as st

SIGNS = ('1', 'X', '2')
API = 'https://api.spela.svenskaspel.se/draw/1'


def read_ticket(raw):
    text = raw.decode('utf-8-sig')
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    header = re.fullmatch(r'(Stryktipset|Europatipset|Topptipset|Powerplay),Omg=(\d+)', lines[0], re.I)
    if not header:
        raise ValueError('Första raden måste ange spelform och Omg=nummer.')
    product = header.group(1).lower()
    count = 13 if product in ('stryktipset', 'europatipset') else 8
    rows = []
    for line in lines[1:]:
        cells = [x.strip().upper() for x in line.split(',')]
        if len(cells) != count + 1 or cells[0] != 'E' or any(c not in SIGNS for c in cells[1:]):
            raise ValueError('TXT-filen innehåller en ogiltig enkelrad.')
        rows.append([SIGNS.index(c) for c in cells[1:]])
    if not rows:
        raise ValueError('TXT-filen saknar enkelrader.')
    arr = np.asarray(rows, dtype=np.int8)
    if len(np.unique(arr, axis=0)) != len(arr):
        raise ValueError('TXT-filen innehåller dubbla rader.')
    return product, int(header.group(2)), arr


def read_events(payload, n):
    root = payload.get('result') if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        raise ValueError('Resultat-API gav inte förväntat format.')
    events = root.get('events')
    if not isinstance(events, list) or len(events) != n:
        raise ValueError('API gav inte rätt antal matcher.')
    out = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ValueError('Ogiltig matchdata.')
        nr = ev.get('eventNumber')
        if nr is not None and str(nr) != str(i + 1):
            raise ValueError('Matchordningen i API behöver verifieras.')
        sign = str(ev.get('outcome') or '').upper()
        score = ev.get('outcomeScore') or {}
        if not isinstance(score, dict):
            score = {}
        participants = ev.get('participants') or []
        names = {str(p.get('type')).lower(): p.get('name') for p in participants if isinstance(p, dict)}
        out.append({'match': f"{names.get('home', f'Match {i+1}')} – {names.get('away', '')}",
                    'sign': sign if sign in SIGNS else None,
                    'score': f"{score.get('home')}–{score.get('away')}" if score.get('home') is not None and score.get('away') is not None else '—'})
    return out


def calculate(rows, events):
    known = [(i, SIGNS.index(e['sign'])) for i, e in enumerate(events) if e['sign'] in SIGNS]
    misses = np.zeros(len(rows), dtype=int)
    for i, sign in known:
        misses += (rows[:, i] != sign)
    n = rows.shape[1]
    return {'known': len(known), 'best': n - int(misses.min()),
            'counts': {target: int(np.count_nonzero(misses <= n-target)) for target in range(n, n-4, -1)},
            'misses': misses}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_result(product, draw):
    url = f'{API}/{product}/draws/{draw}/result'
    response = requests.get(url, timeout=12, headers={'User-Agent': 'QuantPoolLive/1.0'})
    response.raise_for_status()
    return response.json(), datetime.now(timezone.utc).strftime('%H:%M:%S UTC')


st.set_page_config(page_title='Livekoll – Quant Pool', page_icon='⚽', layout='wide')
st.title('⚽ Livekoll – mina inlämnade rader')
st.caption('Hämtar officiella omgångsresultat automatiskt. Inga resultat behöver skrivas in.')
file = st.file_uploader('Ladda upp den TXT-fil du faktiskt lämnade in', type=['txt'])
if file is None:
    st.info('Välj din TXT-fil för att börja följa systemet.')
    st.stop()
try:
    product, draw, rows = read_ticket(file.getvalue())
except (ValueError, UnicodeDecodeError, IndexError) as exc:
    st.error(str(exc))
    st.stop()
st.write(f'**{product.capitalize()} – omgång {draw} – {len(rows)} rader**')
if st.button('🔄 Hämta senaste resultat nu'):
    fetch_result.clear()
try:
    payload, fetched_at = fetch_result(product, draw)
    events = read_events(payload, rows.shape[1])
except (requests.RequestException, ValueError) as exc:
    st.warning(f'Kan inte verifiera resultat från Svenska Spel just nu: {exc}')
    st.info('Inga rader räknas bort utan verifierade resultat. Försök igen senare.')
    st.stop()

st.caption(f'Senast hämtat från Svenska Spel: {fetched_at}. Resultat-API:et kan publicera utfall först efter avslutad match.')
if all(e['sign'] is None for e in events):
    st.info('Inga officiella 1/X/2-utfall publicerade ännu. Detta är inte en livescore med matchminuter.')
summary = calculate(rows, events)
st.metric('Officiella tecken publicerade', f"{summary['known']}/{len(events)}")
st.metric('Bästa möjliga slutresultat utifrån kända tecken', f"{summary['best']} rätt")
cols = st.columns(4)
for col, (target, count) in zip(cols, summary['counts'].items()):
    col.metric(f'Rader som ännu kan få minst {target} rätt', count)
st.caption('Möjligheter, inte garantier: okända matcher kan ändra utfallet. Ett redan felaktigt tecken kan inte rättas av återstående matcher.')
st.dataframe(pd.DataFrame([{'Nr': i+1, 'Match': e['match'], 'Resultat': e['score'],
                            'Officiellt tecken': e['sign'] or 'Ej publicerat'} for i,e in enumerate(events)]),
             hide_index=True, use_container_width=True)
if summary['known'] == len(events):
    exact = len(events) - summary['misses']
    st.subheader('Slutlig radfördelning')
    st.dataframe(pd.DataFrame({'Rätt': list(range(len(events), -1, -1)),
                               'Antal rader': [int(np.count_nonzero(exact == x)) for x in range(len(events), -1, -1)]}),
                 hide_index=True)
st.warning('Observera: detta API är verifierat för officiella resultat, inte för löpande minut-för-minut-ställningar. Sidan uppdateras vid knapptryckning eller när du öppnar den igen.')
