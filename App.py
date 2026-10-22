import streamlit as st
import requests
import pandas as pd
import itertools

st.set_page_config(page_title="Pool-Assistenten", layout="wide")
st.title("⚽ Pool-Assistenten (EV & Reducering)")

# 1. Välj spel i sidomenyn
product_map = {
    "Stryktipset": "stryktipset",
    "Europatipset": "europatipset",
    "Topptipset": "topptipset",
    "Powerplay": "powerplay"
}
selected_label = st.sidebar.selectbox("Välj spelform", list(product_map.keys()))
product = product_map[selected_label]

@st.cache_data(ttl=120)
def fetch_draws(prod):
    """Hämtar öppna omgångar från Svenska Spels öppna API."""
    url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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

# Om t.ex. Topptipset har flera öppna omgångar samtidigt, låt användaren välja
draw_options = {f"Omgång {d.get('drawNumber')} - {d.get('drawComment', '')}": d for d in draws}
selected_draw_key = st.sidebar.selectbox("Välj omgång", list(draw_options.keys()))
draw = draw_options[selected_draw_key]

if st.sidebar.button("🔄 Uppdatera live-data"):
    st.cache_data.clear()
    st.rerun()

events = draw.get("drawEvents", [])
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    # Hämta streckfördelning (Svenska folket)
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    
    # Hämta aktuella odds
    odds = ev.get("odds") or {}
    o1 = parse_odd(odds.get("one"))
    ox = parse_odd(odds.get("x"))
    o2 = parse_odd(odds.get("two"))
    
    # Räkna ut "sann" sannolikhet i procent (rensat för Svenska Spels marginal)
    if o1 > 0 and ox > 0 and o2 > 0:
        inv1, invx, inv2 = 1/o1, 1/ox, 1/o2
        total_inv = inv1 + invx + inv2
        p1 = round((inv1 / total_inv) * 100, 1)
        px = round((invx / total_inv) * 100, 1)
        p2 = round((inv2 / total_inv) * 100, 1)
    else:
        # Fallback om odds saknas på någon match
        p1, px, p2 = s1, sx, s2

    # Spelvärde (Diff i procentenheter: Sannolikhet minus Streckprocent)
    # Positivt tal = Understreckat (Bra värde!). Negativt = Överstreckat.
    v1 = round(p1 - s1, 1)
    vx = round(px - sx, 1)
    v2 = round(p2 - s2, 1)
    
    match_data.append({
        "Nr": num, "Match": desc,
        "Odds 1": o1, "Odds X": ox, "Odds 2": o2,
        "Sannolikhet 1 (%)": p1, "Sannolikhet X (%)": px, "Sannolikhet 2 (%)": p2,
        "Streck 1 (%)": s1, "Streck X (%)": sx, "Streck 2 (%)": s2,
        "Värde 1": v1, "Värde X": vx, "Värde 2": v2
    })

df = pd.DataFrame(match_data)

# 2. Visa Värdetabell
st.subheader("📊 Analys: Spelvärde (Sannolikhet vs. Svenska Folket)")
st.caption("Grönt = Understreckat (Spelvärde!). Rött = Överstreckat (Dåligt värde).")

def color_value(val):
    if val >= 5:
        return "background-color: #1e4620; color: #a3cfbb; font-weight: bold;"
    elif val <= -5:
        return "background-color: #5c1e1e; color: #f5c2c7;"
    return ""

display_cols = [
    "Nr", "Match", 
    "Streck 1 (%)", "Streck X (%)", "Streck 2 (%)", 
    "Värde 1", "Värde X", "Värde 2"
]
st.dataframe(
    df[display_cols].style.map(color_value, subset=["Värde 1", "Värde X", "Värde 2"]),
    use_container_width=True,
    hide_index=True
)

st.divider()

# 3. Interaktiv Kupong & Reducering
st.subheader("📝 Bygg & Reducera Kupong")

if st.button("⚡ Auto-fyll kupong baserat på spelvärde"):
    for idx, row in df.iterrows():
        m_nr = row["Nr"]
        # Välj tecken som inte är kraftigt överstreckade, eller spika starkaste värdet
        st.session_state[f"m_{m_nr}_1"] = bool(row["Värde 1"] > -3 or row["Sannolikhet 1 (%)"] > 60)
        st.session_state[f"m_{m_nr}_X"] = bool(row["Värde X"] > 2)
        st.session_state[f"m_{m_nr}_2"] = bool(row["Värde 2"] > -3 or row["Sannolikhet 2 (%)"] > 60)
        # Säkerställ att minst ett tecken är valt
        if not any([st.session_state[f"m_{m_nr}_1"], st.session_state[f"m_{m_nr}_X"], st.session_state[f"m_{m_nr}_2"]]):
            best_sign = ["1", "X", "2"][[row["Värde 1"], row["Värde X"], row["Värde 2"]].index(max(row["Värde 1"], row["Värde X"], row["Värde 2"]))]
            st.session_state[f"m_{m_nr}_{best_sign}"] = True

selections = []
for idx, row in df.iterrows():
    m_nr = row["Nr"]
    cols = st.columns([4, 1, 1, 1])
    cols[0].write(f"**{m_nr}. {row['Match']}**")
    
    # Sätt standardvärde (1:a) om inget är iklickat än
    if f"m_{m_nr}_1" not in st.session_state:
        st.session_state[f"m_{m_nr}_1"] = True
        st.session_state[f"m_{m_nr}_X"] = False
        st.session_state[f"m_{m_nr}_2"] = False

    c1 = cols[1].checkbox(f"1 ({int(row['Streck 1 (%)'])}%)", key=f"m_{m_nr}_1")
    cx = cols[2].checkbox(f"X ({int(row['Streck X (%)'])}%)", key=f"m_{m_nr}_X")
    c2 = cols[3].checkbox(f"2 ({int(row['Streck 2 (%)'])}%)", key=f"m_{m_nr}_2")
    
    signs = []
    if c1: signs.append("1")
    if cx: signs.append("X")
    if c2: signs.append("2")
    selections.append(signs)

# 4. Reduceringsvillkor i sidomenyn
num_matches = len(df)
st.sidebar.header("⚙️ Reduceringsvillkor")
min_1, max_1 = st.sidebar.slider("Antal 1:or i systemet", 0, num_matches, (0, num_matches))
min_x, max_x = st.sidebar.slider("Antal X i systemet", 0, num_matches, (0, num_matches))
min_2, max_2 = st.sidebar.slider("Antal 2:or i systemet", 0, num_matches, (0, num_matches))

if all(len(s) > 0 for s in selections):
    # Generera matematiska rader och filtrera
    all_rows = list(itertools.product(*selections))
    filtered_rows = [
        r for r in all_rows
        if (min_1 <= r.count("1") <= max_1)
        and (min_x <= r.count("X") <= max_x)
        and (min_2 <= r.count("2") <= max_2)
    ]
    
    st.info(f"**Matematiska rader:** {len(all_rows)} st ➡️ **Efter reducering:** {len(filtered_rows)} st (Kostnad: {len(filtered_rows)} kr)")
    
    if filtered_rows:
        # Skapa Svenska Spels filformat (E på första raden, sedan kommatecken-separerade rader)
        lines = ["E"] + [",".join(r) for r in filtered_rows]
        file_content = "\n".join(lines)
        
        st.download_button(
            label="📥 Ladda ner systemfil (.txt) för Svenska Spel",
            data=file_content,
            file_name=f"{product}_omg_{draw.get('drawNumber')}.txt",
            mime="text/plain"
        )
else:
    st.warning("Du måste välja minst ett tecken (1, X eller 2) i samtliga matcher.")
      
