"""Quant Pool Pro: automated Svenska Spel fixtures, market model, portfolio and tracking."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from quantpro.auto_data import PRODUCTS, FeedError, fetch_draw, list_draws
from quantpro.pro_analysis import value_table, top_rows, summarize, export_txt, score_rows

st.set_page_config(page_title='Quant Pool Pro Full', page_icon='⚽', layout='wide')
st.title('⚽ Quant Pool Pro')
st.caption('Automatisk kupong • Oddsanalys • Streckvärde • Systembyggare • Kupongkontroll')
st.warning('Analysverktyg, inte ett system som garanterar vinst. Marknadssannolikheter är inte en oberoende AI-prognos. Ingen automatisk spelinlämning.')

@st.cache_data(ttl=120, show_spinner=False)
def cached_draw(product, draw):
    return fetch_draw(product, draw)

@st.cache_data(ttl=120, show_spinner=False)
def cached_draws(product):
    return list_draws(product)

with st.sidebar:
    st.header('Kupong')
    product = st.selectbox('Speltyp', list(PRODUCTS))
    if st.button('Hitta omgångar'):
        try: st.session_state['available_draws'] = cached_draws(product)
        except FeedError as exc: st.error(str(exc))
    available = st.session_state.get('available_draws', [])
    if available:
        st.caption('Senast listade omgångar: '+', '.join(map(str, available[:8])))
    draw = st.number_input('Omgångsnummer', min_value=1, value=4977, step=1)
    if st.button('Hämta / uppdatera', type='primary', use_container_width=True):
        try:
            with st.spinner('Hämtar Svenska Spel…'):
                st.session_state['coupon'] = cached_draw(product, int(draw))
                st.session_state.pop('generated_rows', None)
        except (FeedError, ValueError) as exc:
            st.error(str(exc))
            st.session_state.pop('coupon', None)

coupon = st.session_state.get('coupon')
if not coupon:
    st.info('Välj speltyp och omgång i sidomenyn och tryck **Hämta / uppdatera**. På mobil öppnas sidomenyn med dubbelpilen längst upp till vänster.')
    st.stop()

if coupon['product'] != product or coupon['number'] != int(draw):
    st.info('Du har ändrat spel eller omgång. Tryck **Hämta / uppdatera** för att ladda rätt kupong.')
    st.stop()

matches = coupon['matches']
st.success(f"{product} omgång {coupon['number']} – {len(matches)} matcher hämtade")
st.caption(f"Källa: {coupon['url']} | Hämtad UTC: {coupon['fetched_at']}")
missing_odds = sum(m['odds'] is None for m in matches)
missing_streck = sum(m['streck'] is None for m in matches)
if missing_odds: st.warning(f'{missing_odds} matcher saknar verifierbara 1X2-odds. Systembyggaren kräver odds för samtliga matcher.')
if missing_streck: st.info(f'{missing_streck} matcher saknar verifierbar streckprocent. Dessa visas som saknade, inte som 0 %.')

tab1, tab2, tab3, tab4 = st.tabs(['📋 Kupong', '📊 Matchanalys', '🎯 Systembyggare', '🏁 Resultat'])
with tab1:
    records = []
    for m in matches:
        odds, s = m['odds'], m['streck']
        records.append({'Nr':m['Nr'], 'Hemma':m['Hemma'], 'Borta':m['Borta'],
                        'Odds 1':odds[0] if odds else None, 'Odds X':odds[1] if odds else None, 'Odds 2':odds[2] if odds else None,
                        'Streck 1 %':round(s[0]*100,1) if s else None,
                        'Streck X %':round(s[1]*100,1) if s else None,
                        'Streck 2 %':round(s[2]*100,1) if s else None})
    df = pd.DataFrame(records)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button('Ladda ner kupong CSV', df.to_csv(index=False).encode('utf-8-sig'), f'{product}_{draw}.csv', mime='text/csv')
with tab2:
    number = st.selectbox('Välj match', range(1,len(matches)+1), format_func=lambda i: f"{i}. {matches[i-1]['Hemma']} – {matches[i-1]['Borta']}")
    match = matches[number-1]
    table = value_table(match)
    if not table: st.warning('Oddsen saknas för denna match. Ingen sannolikhetsmodell kan räknas.')
    else:
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
        st.caption('Marknad % = normaliserade implicita sannolikheter från odds. Skillnad pp = marknadssannolikhet minus streckandel. Det är INTE en beräkning av förväntad kontantutdelning på poolspel.')
        if match['streck']:
            best = max(table, key=lambda r: r['Skillnad pp'])
            st.info(f"Störst positiv skillnad: {best['Tecken']} ({best['Skillnad pp']:+.1f} procentenheter).")
with tab3:
    st.subheader('Bygg ett system')
    st.caption('Första strategin väljer de matematiskt mest sannolika exakta raderna utifrån odds. Den optimerar inte poolutdelning eller skrällvärde.')
    stake = st.number_input('Insats per rad (kr)', min_value=0.1, value=1.0, step=0.5)
    budget = st.number_input('Budget (kr)', min_value=1.0, value=300.0, step=50.0)
    count = int(budget // stake)
    st.write(f'Antal rader: **{count}**')
    if count > 10000: st.error('Max 10 000 rader i denna version.')
    elif missing_odds: st.error('Alla matcher behöver odds för att skapa ett automatiskt system. Vi fyller aldrig saknade odds med påhittade värden.')
    elif st.button('Generera rader', type='primary'):
        try: st.session_state['generated_rows'] = top_rows(matches, count)
        except ValueError as exc: st.error(str(exc))
    rows = st.session_state.get('generated_rows')
    if rows and not missing_odds:
        report = summarize(rows, matches)
        st.metric('Modellerad chans till alla rätt', f"{report['chance_13_or_8']*100:.4f} %")
        st.caption('Gäller endast om de oddsbaserade matchprognoserna är korrekta och matcherna kan modelleras som oberoende.')
        dist = pd.DataFrame([{'Nr':i+1, **d} for i,d in enumerate(report['distribution'])])
        st.dataframe(dist, use_container_width=True, hide_index=True)
        st.download_button('Ladda ner TXT-rader', export_txt(rows, product, draw), f'{product}_{draw}_rader.txt', mime='text/plain')
with tab4:
    st.subheader('Kontrollera resultat')
    rows = st.session_state.get('generated_rows')
    if not rows:
        st.info('Generera först ett system under Systembyggare.')
    else:
        st.caption('Ange 1, X, 2 eller ? för okända resultat. Automatisk livehämtning av slutresultat ingår ännu inte.')
        inputs = []
        for i,m in enumerate(matches):
            inputs.append(st.selectbox(f"{i+1}. {m['Hemma']} – {m['Borta']}", ['?', '1','X','2'], key=f'result_{product}_{draw}_{i}'))
        if st.button('Beräkna antal rätt'):
            result = score_rows(rows, inputs)
            st.metric('Kända matcher', result['known'])
            st.metric('Högsta möjliga rätt', result['max_possible'])
            st.dataframe(pd.DataFrame([{'Rätt på avgjorda matcher': k, 'Rader':v} for k,v in result['distribution'].items()]), hide_index=True)
