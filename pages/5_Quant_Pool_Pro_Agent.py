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
from quantpro.research import FootballResearch, ResearchError
from quantpro.agent import forecast
from quantpro.memory import Store, utcnow
from quantpro.backtest import score_history

st.set_page_config(page_title='Quant Pool Pro Agent',page_icon='🧠',layout='wide')
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
        if hmac.compare_digest(supplied, str(password)):
            st.session_state['authenticated']=True
            st.rerun()
        else: st.error('Fel lösenord')
    st.stop()

@st.cache_data(ttl=120,show_spinner=False)
def get_coupon(product,number): return fetch_draw(product,number)

with st.sidebar:
    st.header('Inställningar')
    product=st.selectbox('Spel',list(PRODUCTS))
    draw=st.number_input('Omgång',min_value=1,value=4977,step=1)
    if st.button('Hämta kupong',type='primary'):
        try:
            st.session_state['agent_coupon']=get_coupon(product,int(draw))
            st.session_state.pop('agent_rows',None)
            st.session_state.pop('agent_reports',None)
            st.session_state.pop('agent_snapshot_id',None)
        except (FeedError,ValueError) as exc: st.error(str(exc))
    if st.button('Logga ut'):
        st.session_state['authenticated']=False
        st.rerun()
    st.caption('Databas: '+('PostgreSQL (beständig)' if secret('DATABASE_URL') else 'SQLite (tillfällig på Streamlit Cloud)'))

try:
    store=Store(url=secret('DATABASE_URL') or None)
except Exception as exc:
    st.error(f'Databasen kunde inte öppnas: {exc}')
    st.stop()

coupon=st.session_state.get('agent_coupon')
if not coupon or coupon['product']!=product or coupon['number']!=int(draw):
    st.info('Välj spel och omgång i sidomenyn och tryck Hämta kupong.')
    st.stop()

matches=coupon['matches']
st.success(f"{product} #{draw}: {len(matches)} matcher. Hämtad {coupon['fetched_at']} UTC")
st.caption('Källa: '+coupon['url'])

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
    st.dataframe(pd.DataFrame(display),hide_index=True,use_container_width=True)
    st.download_button('Exportera kupong CSV',pd.DataFrame(display).to_csv(index=False).encode('utf-8-sig'),f'{product}_{draw}.csv')
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

with research_tab:
    st.write('Hämta verifierad lagform från API-Football. Lagidentifiering måste vara exakt; felaktiga lagmatchningar avvisas.')
    key=secret('API_FOOTBALL_KEY')
    if not key: st.info('Lägg till API_FOOTBALL_KEY i Streamlit Secrets för att aktivera research.')
    choice=st.selectbox('Researchmatch',list(range(len(matches))),format_func=lambda i:f"{i+1}. {matches[i]['Hemma']} – {matches[i]['Borta']}")
    h=st.text_input('Hemma (API-Football-namn)',value=matches[choice]['Hemma'])
    a=st.text_input('Borta (API-Football-namn)',value=matches[choice]['Borta'])
    if st.button('Undersök match',disabled=not bool(key)):
        try:
            report=FootballResearch(key).report(h,a)
            st.session_state.setdefault('agent_reports',{})[choice]=report
        except ResearchError as exc: st.error(str(exc))
    report=st.session_state.get('agent_reports',{}).get(choice)
    if report:
        st.json(report,expanded=False)
        st.caption('Källa och tidsstämpel ingår. Ej tillgänglig research fylls inte ut med AI-gissningar.')

with system_tab:
    missing=sum(m['odds'] is None for m in matches)
    budget=st.number_input('Budget (kr)',min_value=1,max_value=10000,value=300,step=50)
    stake=st.number_input('Insats per rad (kr)',min_value=0.1,max_value=100,value=1.0,step=0.5)
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
