"""Automatic coupon retrieval, deliberately no invented odds/streck."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from quantpro.svenska_spel import PRODUCTS, FeedError, fetch_coupon

st.set_page_config(page_title='Automatisk kupong', page_icon='⚽')
st.title('⚽ Automatisk kupong')
st.info('Experimentell koppling till Svenska Spels öppna omgångsdata. Odds och streck visas inte förrän API-fälten är verifierade.')
name = st.selectbox('Spel', list(PRODUCTS))
draw = st.number_input('Omgångsnummer', min_value=1, value=4977, step=1)
if st.button('Hämta kupong', type='primary'):
    try:
        coupon = fetch_coupon(PRODUCTS[name], draw)
    except (FeedError, ValueError) as exc:
        st.error(str(exc))
        st.caption('Om Svenska Spel ändrat format behöver vi uppdatera adaptern. Ingen gammal eller påhittad kupong visas.')
    else:
        st.success(f"Hämtade {len(coupon['matches'])} matcher")
        st.caption(f"Källa: {coupon['source']} · Hämtad UTC: {coupon['fetched_utc']}")
        st.dataframe(pd.DataFrame(coupon['matches']), use_container_width=True, hide_index=True)
        st.download_button('Exportera matcher (CSV)', pd.DataFrame(coupon['matches']).to_csv(index=False).encode('utf-8-sig'), 'kupong.csv', 'text/csv')
