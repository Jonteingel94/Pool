"""Quant Pool Pro Agent: source-aware research, forecasts, portfolios, persistent history."""
import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st
from quantpro.auto_data import PRODUCTS, fetch_draw, list_draws, FeedError
from quantpro.pro_analysis import top_rows, summarize, export_txt, value_table
from quantpro.public_research import load_results, analyze_match, PublicResearchError
from quantpro.agent import forecast
from quantpro.memory import Store, utcnow
from quantpro.backtest import score_history

st.set_page_config(page_title='Quant Pool Pro Agent',page_icon='🧠',layout='wide')
st.markdown("""
<style>
/* Compact, touch-friendly layout on phones. */
.block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1200px; }
div.stButton > button, div.stDownloadButton > button,
div[data-testid="stFormSubmitButton"] button {
    min-height: 44px; border-radius: 12px; font-weight: 600;
}
div[data-baseweb="select"] > div,
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input { min-height: 44px; }
div[data-testid="stAlert"] { border-radius: 12px; }
div[data-testid="stDataFrame"] { max-width: 100%; }
@media (max-width: 700px) {
    .block-container { padding: .75rem .85rem 4.5rem; }
    h1 { font-size: 1.65rem !important; line-height: 1.2 !important; }
    h2 { font-size: 1.25rem !important; }
    h3 { font-size: 1.1rem !important; }
    div[data-testid="stHorizontalBlock"] { gap: .55rem; }
    div[data-testid="stTabs"] button { padding: .6rem .7rem; font-size: .87rem; }
    div[data-testid="stDataFrame"] { overflow-x: auto; }
    div.stButton > button, div.stDownloadButton > button { width: 100%; }
    div[data-testid="stMetric"] { padding: .5rem 0; }
}
</style>
""", unsafe_allow_html=True)

st.title('🧠 Quant Pool Pro Agent')
st.caption('Kuponger • Marknadsanalys • Verifierad formresearch • System • Historik • Backtesting')
st.warning('Inga garanterade vinster. AI-research och formjustering är inte en bevisat lönsam prognos. Inga spel placeras automatiskt.')

# Streamlit Community Cloud is public by default. Require app password before DB access.
secret=lambda name: st.secrets.get(name,os.getenv(name,''))
password=secret('APP_PASSWORD')
if not password:
    st.error('APP_PASSWORD måste anges i Streamlit Secrets innan agenten kan användas. Detta skyddar databas och API-kvoter.')
    st.stop()
if not st.session_state.get('authenticated'):
    supplied=st.text_input('App-lösenord',type='password')
    if st.button('Logga in'):
        import hmac
        if hmac.compare_digest(str(supplied).encode("utf-8"), str(password).encode("utf-8")):
            st.session_state['authenticated']=True
            st.rerun()
        else: st.error('Fel lösenord')
    st.stop()

@st.cache_data(ttl=120,show_spinner=False)
def get_coupon(product,number): return fetch_draw(product,number)

@st.cache_data(ttl=300, show_spinner=False)
def available_draws(product):
    """Read real draw numbers; never invent numbers when the feed fails."""
    return list_draws(product)

st.subheader('🎟️ Välj kupong')
st.caption('Välj spel och omgång här direkt på mobilen – du behöver inte öppna sidomenyn.')
product=st.selectbox('Spel', list(PRODUCTS), key='agent_product')
draw_options = []
draw_error = None
try:
    draw_options = available_draws(product)
except (FeedError, ValueError, TypeError, KeyError) as exc:
    draw_error = str(exc)

if draw_options:
    draw = st.selectbox(
        'Omgång', options=draw_options,
        format_func=lambda number: f'Omgång {number}',
        key=f'agent_draw_{product}',
    )
    st.caption(f'{len(draw_options)} omgångar hittades. Kontrollera spelstopp före spel.')
else:
    st.warning('Automatisk omgångslista saknas.' + (f' {draw_error}' if draw_error else ''))
    draw = st.number_input(
        'Omgång (manuellt)', min_value=1, value=1, step=1,
        key=f'agent_manual_draw_{product}',
    )

fetch_col, refresh_col = st.columns(2)
with fetch_col:
    fetch_pressed = st.button('📥 Hämta kupong', type='primary', use_container_width=True)
with refresh_col:
    refresh_pressed = st.button('🔄 Uppdatera', use_container_width=True)
if refresh_pressed:
    available_draws.clear()
    get_coupon.clear()
    st.rerun()
if fetch_pressed:
    try:
        st.session_state['agent_coupon'] = get_coupon(product, int(draw))
        st.session_state.pop('agent_rows', None)
        st.session_state.pop('agent_reports', None)
        st.session_state.pop('agent_public_reports', None)
        st.session_state.pop('agent_snapshot_id', None)
    except (FeedError, ValueError) as exc:
        st.error(str(exc))

with st.sidebar:
    st.header('⚙️ Inställningar')
    st.caption('Appen är anpassad för mobil. Kupongval finns på startsidan.')
    if st.button('Logga ut', use_container_width=True):
        st.session_state['authenticated'] = False
        st.rerun()
    st.caption('Databas: ' + ('PostgreSQL (beständig)' if secret('DATABASE_URL') else 'SQLite (tillfällig på Streamlit Cloud)'))

try:
    store=Store(url=secret('DATABASE_URL') or None)
except Exception as exc:
    st.error(f'Databasen kunde inte öppnas: {exc}')
    st.stop()

coupon=st.session_state.get('agent_coupon')
if not coupon or coupon['product']!=product or coupon['number']!=int(draw):
    st.info('Välj spel och omgång ovan och tryck Hämta kupong.')
    st.stop()

matches=coupon['matches']
st.success(f"{product} #{draw}: {len(matches)} matcher. Hämtad {coupon['fetched_at']} UTC")
st.caption('Källa: '+coupon['url'])
st.info('📱 Välj en flik nedan. Svep sidledes över flikarna om inte alla syns.')

coupon_tab,analysis_tab,research_tab,system_tab,history_tab=st.tabs(['📋 Kupong','📊 Analys','🔎 Research','🎯 System','🗄️ Minne & test'])
with coupon_tab:
    display=[]
    for m in matches:
        o=m['odds']; s=m['streck']
        display.append({'Nr':m['Nr'],'Hemma':m['Hemma'],'Borta':m['Borta'],
            'Odds 1':o[0] if o else None,'Odds X':o[1] if o else None,'Odds 2':o[2] if o else None,
            'Streck 1 %':round(100*s[0],1) if s else None,
            'Streck X %':round(100*s[1],1) if s else None,
            'Streck 2 %':round(100*s[2],1) if s else None})
    st.dataframe(
        pd.DataFrame(display),
        hide_index=True, use_container_width=True, height=390,
        column_config={
            'Nr': st.column_config.NumberColumn('Nr', width='small'),
            'Hemma': st.column_config.TextColumn('Hemma', width='medium'),
            'Borta': st.column_config.TextColumn('Borta', width='medium'),
        },
    )
    st.caption('↔ Svep i tabellen för att se odds och streckprocent.')
    st.download_button('📥 Exportera kupong CSV',pd.DataFrame(display).to_csv(index=False).encode('utf-8-sig'),f'{product}_{draw}.csv')
    if st.button('💾 Spara tidsstämplad kupong'):
        key=hashlib.sha256(f"{product}:{draw}:{coupon['fetched_at']}".encode()).hexdigest()[:24]
        try:
            store.put('snapshots',key,{'product':product,'draw':draw,'captured_at':coupon['fetched_at'],'source':coupon['url']},coupon)
            st.session_state['agent_snapshot_id']=key
            st.success('Kupongen sparad. Snapshot-ID: '+key)
        except Exception as exc: st.error(str(exc))

with analysis_tab:
    choice=st.selectbox('Match',list(range(len(matches))),format_func=lambda i:f"{i+1}. {matches[i]['Hemma']} – {matches[i]['Borta']}")
    match=matches[choice]
    if match['odds']:
        st.dataframe(pd.DataFrame(value_table(match)),hide_index=True,use_container_width=True)
        report=st.session_state.get('agent_reports',{}).get(choice)
        model=forecast(match,report)
        st.caption('Prognos = marknadsbaslinje. Research visas separat och påverkar inte automatiskt sannolikheterna.')
        st.write('Marknadssannolikheter:',dict(zip(('1','X','2'),[round(x*100,2) for x in model['market']])))
    else: st.warning('Verifierbara odds saknas för denna match.')
    st.subheader('Arkivera prognoser före spelstopp')
    st.caption('Ange officiell spelstopptid i UTC (ISO 8601). En prognos arkiveras bara om samtliga matcher har odds och spelstopp ligger efter hämtningstidpunkten.')
    cutoff_text=st.text_input('Spelstopp UTC',value='',placeholder='2026-11-07T14:59:00+00:00')
    if st.button('Spara marknadsprognoser'):
        snapshot_id=st.session_state.get('agent_snapshot_id')
        if not snapshot_id: st.error('Spara kupongögonblicket först på Kupong-fliken.')
        elif any(m['odds'] is None for m in matches): st.error('Oddsen saknas för någon match.')
        else:
            try:
                from datetime import datetime,timezone
                cutoff=datetime.fromisoformat(cutoff_text)
                captured=datetime.fromisoformat(coupon['fetched_at'])
                if cutoff.tzinfo is None or captured>=cutoff: raise ValueError('Spelstopp måste vara tidszonsatt och ligga efter hämtningen')
                probs=[forecast(m)['model'] for m in matches]
                when=utcnow()
                key=hashlib.sha256(f'{snapshot_id}:{when}:forecast'.encode()).hexdigest()[:24]
                store.put('forecasts',key,{'snapshot_id':snapshot_id,'name':'market-baseline-v1','created_at':when},
                    {'product':product,'draw':int(draw),'captured_at':coupon['fetched_at'],
                     'cutoff_at':cutoff.isoformat(),'probabilities':probs,'model':'market-baseline-v1'})
                st.success('Prognoserna arkiverade för framtida backtesting.')
            except (ValueError,TypeError) as exc: st.error(f'Ogiltig spelstopptid: {exc}')
            except Exception as exc: st.error(str(exc))

@st.cache_data(ttl=21600,show_spinner=False)
def public_results():
    return load_results()

with research_tab:
    st.subheader('🔎 Research utan API-nyckel')
    st.caption('Källa: football-data.co.uk. Offentliga matchresultat för utvalda europeiska ligor. Sverige och vissa cupmatcher kan saknas.')
    if st.button('🔎 Starta fullständig research',type='primary',use_container_width=True):
        try:
            with st.spinner('Hämtar och jämför matchhistorik... Detta kan ta en stund första gången.'):
                history,load_warnings=public_results()
                reports={}
                progress=st.progress(0)
                for i,m in enumerate(matches):
                    reports[i]=analyze_match(m['Hemma'],m['Borta'],history)
                    progress.progress((i+1)/len(matches))
                st.session_state['agent_public_reports']=reports
                st.session_state['agent_public_warnings']=load_warnings
            st.success(f'Research klar: {sum(r["status"]=="ok" for r in reports.values())} av {len(matches)} matcher hittades med entydig lagmatchning.')
        except (PublicResearchError,Exception) as exc:
            st.error(f'Research kunde inte slutföras: {exc}')
    reports=st.session_state.get('agent_public_reports',{})
    if reports:
        overview=[]
        for i,m in enumerate(matches):
            r=reports.get(i,{})
            hf=r.get('home_form',{}); af=r.get('away_form',{})
            overview.append({'Nr':i+1,'Match':f"{m['Hemma']} – {m['Borta']}",
                             'Status':'Verifierad matchhistorik' if r.get('status')=='ok' else 'Saknar data',
                             'Hemma PPG':hf.get('points_per_game'),'Borta PPG':af.get('points_per_game')})
        st.dataframe(pd.DataFrame(overview),hide_index=True,use_container_width=True)
        i=st.selectbox('Visa matchresearch',range(len(matches)),format_func=lambda i:f"{i+1}. {matches[i]['Hemma']} – {matches[i]['Borta']}")
        st.json(reports.get(i,{}),expanded=False)
        st.download_button('📥 Ladda ner research JSON',json.dumps(reports,ensure_ascii=False,indent=2).encode('utf-8'),f'{product}_{draw}_research.json',mime='application/json')
        st.warning('Skador, avstängningar och startelvor verifieras inte av denna datakälla. Researchen visas som beslutsunderlag och ändrar INTE automatiskt systemgeneratorns sannolikheter.')
        if st.session_state.get('agent_public_warnings'):
            with st.expander('Datakällor som inte kunde läsas'):
                st.write(st.session_state['agent_public_warnings'])
    else:
        st.info('Tryck på knappen för att undersöka alla matcher. Ingen API-nyckel behövs.')

with system_tab:
    missing=sum(m['odds'] is None for m in matches)
    budget=st.number_input('Budget (kr)',min_value=1,max_value=10000,value=300,step=50)
    stake=st.number_input('Insats per rad (kr)',min_value=0.1,max_value=100.0,value=1.0,step=0.5)
    count=int(budget//stake)
    st.write(f'Antal rader: **{count}**')
    if missing: st.warning(f'{missing} matcher saknar odds. Kan inte bygga ett pålitligt system.')
    elif count>10000: st.warning('Max 10 000 rader.')
    elif st.button('Generera sannolikhetsbaserat system'):
        try:
            st.session_state['agent_rows']=top_rows(matches,count)
        except ValueError as exc: st.error(str(exc))
    rows=st.session_state.get('agent_rows')
    if rows and not missing:
        stats=summarize(rows,matches)
        st.metric('Modellerad chans till alla rätt',f"{stats['chance_13_or_8']*100:.4f} %")
        st.caption('Maximerar sannolikhet för alla rätt enligt oddsbaslinjen. Optimerar INTE för verklig poolutdelning.')
        st.dataframe(pd.DataFrame([{'Nr':i+1,**d} for i,d in enumerate(stats['distribution'])]),hide_index=True)
        st.download_button('Ladda ned Svenska Spel TXT',export_txt(rows,product,int(draw)),f'{product}_{draw}_rader.txt')
        if st.button('💾 Spara system i historiken'):
            snapshot_id=st.session_state.get('agent_snapshot_id')
            if not snapshot_id: st.warning('Spara först kupongen på fliken Kupong.')
            else:
                when=utcnow(); key=hashlib.sha256(f'{snapshot_id}:{when}:rows'.encode()).hexdigest()[:24]
                try:
                    store.put('portfolios',key,{'snapshot_id':snapshot_id,'name':'top-probability','created_at':when},
                        {'product':product,'draw':draw,'rows':rows,'budget':budget,'stake':stake,'chance':stats['chance_13_or_8']})
                    st.success('System sparat i databasen')
                except Exception as exc: st.error(str(exc))

with history_tab:
    st.subheader('Historik')
    st.caption('För beständig lagring på Streamlit Cloud krävs DATABASE_URL till PostgreSQL/Supabase.')
    try:
        snapshots=store.list('snapshots'); portfolios=store.list('portfolios'); outcomes=store.list('outcomes')
        st.metric('Sparade kupongögonblick',len(snapshots));st.metric('Sparade system',len(portfolios))
        st.dataframe(pd.DataFrame([{k:v for k,v in r.items() if k!='payload'} for r in snapshots]),hide_index=True)
    except Exception as exc: st.error(str(exc))
    st.subheader('Registrera slutresultat')
    st.caption('Manuell verifiering i denna version. Inga slutresultat hämtas automatiskt ännu.')
    with st.form('results_form'):
        results=[st.selectbox(f"{m['Nr']}. {m['Hemma']} – {m['Borta']}",['?','1','X','2'],key=f'agent_result_{product}_{draw}_{i}') for i,m in enumerate(matches)]
        submitted=st.form_submit_button('Spara resultat')
    if submitted:
        if '?' in results: st.error('Alla matcher måste vara slutspelade innan resultatet sparas.')
        else:
            when=utcnow(); key=f'{product}-{draw}'
            try:
                store.put('outcomes',key,{'product':product,'draw':draw,'recorded_at':when},{'results':results,'source':'manuellt registrerat; verifiera mot officiellt resultat'})
                st.success('Resultatet sparat')
            except Exception as exc: st.error(str(exc))
    st.subheader('Backtesting')
    st.caption('Brier-utvärdering kräver sparade prognoser och verifierade slutresultat, samt tidsstämplar före spelstopp.')
    try:
        evaluated=score_history(store.list('forecasts'),store.list('outcomes'))
        if evaluated: st.dataframe(pd.DataFrame(evaluated),hide_index=True)
        else: st.info('Ingen fullständig prognoshistorik ännu. Nästa steg är automatiskt prognosarkiv med spelstopptider.')
    except Exception as exc: st.error(str(exc))
