"""Quant Pool Pro: transparent first-step research and 1X2 pricing workspace."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from quantpro.engine import analyze_match, score_rows

st.set_page_config(page_title='Quant Pool Pro', page_icon='⚽', layout='wide')
st.title('⚽ Quant Pool Pro')
st.caption('Forsknings- och analysverktyg. Inga liveuppgifter visas utan verifierad datakälla.')
section = st.radio('Analys', ['1X2 och spelvärde', 'Kupongkontroll'], horizontal=True)
if section == '1X2 och spelvärde':
    match = st.text_input('Match', 'Hemmalag – Bortalag')
    st.subheader('Marknadsodds')
    c1,c2,c3 = st.columns(3)
    odds = [c1.number_input('1', min_value=1.01, value=2.00, step=.05),
            c2.number_input('X', min_value=1.01, value=3.40, step=.05),
            c3.number_input('2', min_value=1.01, value=3.80, step=.05)]
    st.subheader('Streckprocent – valfritt')
    use_streck = st.checkbox('Ange streckprocent')
    public = None
    if use_streck:
        a,b,c = st.columns(3)
        public = [a.number_input('Streck 1', 0., 100., 50.),
                  b.number_input('Streck X', 0., 100., 25.),
                  c.number_input('Streck 2', 0., 100., 25.)]
    use_model = st.checkbox('Ange egen modellprognos (annars används marknadsprognos)')
    model = None
    if use_model:
        a,b,c = st.columns(3)
        model = [a.number_input('Modell 1', 0.01, 100., 50.),
                 b.number_input('Modell X', 0.01, 100., 25.),
                 c.number_input('Modell 2', 0.01, 100., 25.)]
    if st.button('Analysera match', type='primary'):
        try:
            df = pd.DataFrame(analyze_match(odds, public, model))
            st.subheader(match)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption('Streckvärde är modellens sannolikhet minus streckandel. Det är inte en garanti för vinst. Marknadsprognosen är normaliserade implicita odds och ingen självständig modell.')
        except ValueError as exc:
            st.error(str(exc))
else:
    st.write('Ladda upp Svenska Spel TXT med E-rader och kontrollera utfall.')
    uploaded = st.file_uploader('Kupongfil', type=['txt'])
    result_str = st.text_input('Resultat (13 tecken 1/X/2; använd ? för ej färdigspelad)', '?????????????').strip().upper()
    if uploaded is not None and st.button('Kontrollera kupongen'):
        try:
            rows = []
            for line in uploaded.getvalue().decode('utf-8-sig').splitlines():
                parts = [x.strip().upper() for x in line.split(',')]
                if parts[0] == 'E': rows.append(parts[1:])
            results = [None if x == '?' else x for x in result_str]
            scored = score_rows(rows, results)
            df = pd.DataFrame(scored)
            st.metric('Antal rader', len(rows))
            st.metric('Högsta möjliga antal rätt', int(df['max_rätt'].max()))
            st.dataframe(df.value_counts().reset_index(name='Antal rader'), use_container_width=True, hide_index=True)
        except (ValueError, UnicodeError, IndexError) as exc:
            st.error(f'Kunde inte analysera filen: {exc}')
