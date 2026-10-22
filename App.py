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

# Sätt automatiska värden i session state baserat på strategi
if st.sidebar.button("⚡ Fyll i kupongen automatiskt åt mig"):
    for idx, row in df.iterrows():
        m_nr = row["Nr"]
        s1, sx, s2 = row["s1"], row["sx"], row["s2"]
        v1, v2 = row["v1"], row["v2"]
        tt1, tt2 = row["tt1"], row["tt2"]
        
        if strategy == "Säker (Spikar favoriter / Flest rätt)":
            # Spika den med högst streck eller expertstöd
            st.session_state[f"m_{m_nr}_1"] = bool(s1 >= max(s1, sx, s2) or tt1 >= 6)
            st.session_state[f"m_{m_nr}_X"] = bool(sx >= 35) # Ta med kryss om det är jämnt
            st.session_state[f"m_{m_nr}_2"] = bool(s2 >= max(s1, sx, s2) or tt2 >= 6)
            
        elif strategy == "Hög Utdelning / Jägaren (Fångar skrällar)":
            # Fäll överstreckade favoriter, gardera hårt eller välj värdetecken
            st.session_state[f"m_{m_nr}_1"] = bool(v1 >= 0 or s1 < 45)
            st.session_state[f"m_{m_nr}_X"] = True  # Alltid kryss för att rensa
            st.session_state[f"m_{m_nr}_2"] = bool(v2 >= 0 or s2 < 45)
            
        else:  # Balanserad
            st.session_state[f"m_{m_nr}_1"] = bool(v1 >= -3 or tt1 >= 5)
            st.session_state[f"m_{m_nr}_X"] = bool(sx >= 25 or v2 >= 3)
            st.session_state[f"m_{m_nr}_2"] = bool(v2 >= -3 or tt2 >= 5)
            
        # Säkerställ att minst ett tecken alltid är valt per match
        if not any([st.session_state[f"m_{m_nr}_1"], st.session_state[f"m_{m_nr}_X"], st.session_state[f"m_{m_nr}_2"]]):
            st.session_state[f"m_{m_nr}_1"] = True

# 2. Visa Matcher & Interaktiv Kupong
st.subheader("📝 Kvällens Kupong & Rader")
st.caption("Assistenten har fyllt i tecknen åt dig baserat på vald strategi. Du kan ändra manuellt om du vill!")

selections = []
for idx, row in df.iterrows():
    m_nr = row["Nr"]
    cols = st.columns([4, 1, 1, 1])
    cols[0].write(f"**{m_nr}. {row['Match']}** (Folket: {int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2']}%)")
    
    # Initiera om saknas
    if f"m_{m_nr}_1" not in st.session_state:
        st.session_state[f"m_{m_nr}_1"] = True
        st.session_state[f"m_{m_nr}_X"] = False
        st.session_state[f"m_{m_nr}_2"] = False

    c1 = cols[1].checkbox("1", key=f"m_{m_nr}_1")
    cx = cols[2].checkbox("X", key=f"m_{m_nr}_X")
    c2 = cols[3].checkbox("2", key=f"m_{m_nr}_2")
    
    signs = []
    if c1: signs.append("1")
    if cx: signs.append("X")
    if c2: signs.append("2")
    selections.append(signs)

num_matches = len(df)
st.sidebar.header("⚙️ Finjustering av rader")
min_1, max_1 = st.sidebar.slider("Antal 1:or", 0, num_matches, (0, num_matches))
min_x, max_x = st.sidebar.slider("Antal X", 0, num_matches, (0, num_matches))
min_2, max_2 = st.sidebar.slider("Antal 2:or", 0, num_matches, (0, num_matches))

if all(len(s) > 0 for s in selections):
    all_rows = list(itertools.product(*selections))
    filtered_rows = [
        r for r in all_rows
        if (min_1 <= r.count("1") <= max_1)
        and (min_x <= r.count("X") <= max_x)
        and (min_2 <= r.count("2") <= max_2)
    ]
    
    total_cost = len(filtered_rows) * stake
    st.info(f"**Matematiska rader:** {len(all_rows)} st ➡️ **Efter filter:** {filtered_rows.__len__()} st (Total kostnad: {total_cost} kr)")
    
    if filtered_rows:
        header_line = f"{selected_label},Omg={draw_number},Insats={stake}"
        lines = [header_line] + [f"E," + ",".join(r) for r in filtered_rows]
        file_content = "\n".join(lines)
        
        st.download_button(
            label="📥 Ladda ner godkänd systemfil (.txt) för Svenska Spel",
            data=file_content,
            file_name=f"{product}_omg_{draw_number}.txt",
            mime="text/plain"
        )
else:
    st.warning("Vänligen välj minst ett tecken per match.")
