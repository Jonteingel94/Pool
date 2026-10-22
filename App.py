import streamlit as st
import requests
import pandas as pd
import itertools

st.set_page_config(page_title="Pool-Assistenten - Auto Edition", layout="wide")
st.title("🏒 Powerplay- & Pool-Assistenten")
st.markdown("Din autonoma expert som bygger raderna åt dig automatiskt beroende på vilken strategi du väljer!")

# 1. Välj spel i sidomenyn
product_map = {
    "Powerplay": "powerplay",
    "Stryktipset": "stryktipset",
    "Europatipset": "europatipset",
    "Topptipset": "topptipset"
}
selected_label = st.sidebar.selectbox("Välj spelform", list(product_map.keys()))
product = product_map[selected_label]

stake = st.sidebar.slider("Insats per rad (kr)", 1, 10, 1)

@st.cache_data(ttl=120)
def fetch_draws(prod):
    url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("draws", [])
    except Exception as e:
        st.error(f"Kunde inte hämta data från Svenska Spel: {e}")
        return []

def parse_odd(val):
    if not val:
        return 0.0
    return float(str(val).replace(",", "."))

draws = fetch_draws(product)

if not draws:
    st.warning("Ingen öppen omgång hittades just nu för detta spel.")
    st.stop()

draw_options = {f"Omgång {d.get('drawNumber')} - {d.get('drawComment', '')}": d for d in draws}
selected_draw_key = st.sidebar.selectbox("Välj omgång", list(draw_options.keys()))
draw = draw_options[selected_draw_key]
draw_number = draw.get('drawNumber')

if st.sidebar.button("🔄 Uppdatera live-data"):
    st.cache_data.clear()
    st.rerun()

events = draw.get("drawEvents", [])
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    
    tt = ev.get("tioTidningarsTips") or {}
    tt1 = int(tt.get("one", 0) or 0)
    ttx = int(tt.get("x", 0) or 0)
    tt2 = int(tt.get("two", 0) or 0)
    
    odds = ev.get("odds") or {}
    o1 = parse_odd(odds.get("one"))
    ox = parse_odd(odds.get("x"))
    o2 = parse_odd(odds.get("two"))
    
    if o1 > 0 and ox > 0 and o2 > 0:
        inv1, invx, inv2 = 1/o1, 1/ox, 1/o2
        total_inv = inv1 + invx + inv2
        p1 = round((inv1 / total_inv) * 100, 1)
        px = round((invx / total_inv) * 100, 1)
        p2 = round((inv2 / total_inv) * 100, 1)
    else:
        p1, px, p2 = s1, sx, s2

    v1 = round(p1 - s1, 1)
    vx = round(px - sx, 1)
    v2 = round(p2 - s2, 1)
    
    match_data.append({
        "Nr": num, "Match": desc,
        "s1": s1, "sx": sx, "s2": s2,
        "p1": p1, "px": px, "p2": p2,
        "v1": v1, "vx": vx, "v2": v2,
        "tt1": tt1, "tt2": tt2
    })

df = pd.DataFrame(match_data)

# --- AUTOMATISKA SPELTYPER & STRATEGIER ---
st.sidebar.divider()
st.sidebar.subheader("🤖 Automatiska Strategier")
strategy = st.sidebar.radio(
    "Välj hur assistenten ska spela åt dig:",
    [
        "Balanserad (Blandat värde)", 
        "Säker (Spikar favoriter / Flest rätt)", 
        "Hög Utdelning / Jägaren (Fångar skrällar)"
    ]
)

if st.sidebar.button("⚡ Fyll i kupongen automatiskt åt mig"):
    for idx, row in df.iterrows():
        m_nr = row["Nr"]
        s1, sx, s2 = row["s1"], row["sx"], row["s2"]
        v1, v2 = row["v1"], row["v2"]
        tt1, tt2 = row["tt1"], row["tt2"]
        
        if strategy == "Säker (Sp
