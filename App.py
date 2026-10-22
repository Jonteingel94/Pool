import streamlit as st
import requests
import pandas as pd
import itertools

st.set_page_config(page_title="Pool-Assistenten", layout="wide")
st.title("⚽ Din Pool-Assistent & Expertanalytiker")
st.markdown("Din personliga rådgivare som kombinerar marknadsodds, Svenska folket och Tio Tidningars Tips (TT) för att hitta bästa spelvärdet.")

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

if st.sidebar.button("🔄 Uppdatera live-data"):
    st.cache_data.clear()
    st.rerun()

events = draw.get("drawEvents", [])
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    # Svenska folket
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    
    # Tio Tidningars Tips (TT)
    tt = ev.get("tioTidningarsTips") or {}
    tt1 = int(tt.get("one", 0) or 0)
    ttx = int(tt.get("x", 0) or 0)
    tt2 = int(tt.get("two", 0) or 0)
    
    # Odds
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
    
    # --- EXPERTANALYS & MOTIVERING MED TT ---
    advice = "Avvakta / Normal"
    reason = "Inga större avvikelser mellan odds, folket och experterna."
    
    if tt1 >= 8:
        if v1 >= 0:
            advice = "🔥 Stabil Spik (1)"
            reason = f"Både experterna ({tt1}/10 tidningar) och oddsen stöder hemmalaget med bra spelvärde."
        else:
            advice = "⚠️ Expertiserad Favorit (Varning)"
            reason = f"Experterna spikar ({tt1}/10), men folket har överstreckat den till {s1}%. Risk för rens om den missar."
    elif tt2 >= 8:
        if v2 >= 0:
            advice = "🔥 Stabil Spik (2)"
            reason = f"Experterna gillar bortalaget starkt ({tt2}/10 tidningar) och oddsen motiverar det."
        else:
            advice = "⚠️ Överstreckad bortafavorit (Varning)"
            reason = f"Experterna tror på bortalaget ({tt2}/10), men strecken är höga ({s2}%). Gardering rekommenderas."
    elif v1 >= 5:
        advice = "💡 Värdespik (1)"
        reason = f"Hemmalaget är undervärderat av folket ({s1}% streck vs {p1}% sannolikhet)."
    elif v2 >= 5:
        advice = "💡 Värdespik (2)"
        reason = f"Bortalaget är undervärderat av folket ({s2}% streck vs {p2}% sannolikhet)."
    elif vx >= 4:
        advice = "💎 Värdekryss (X)"
        reason = f"Krysset är streckat på {sx}%, men oddsen visar hela {px}% chans."

    match_data.append({
        "Nr": num, "Match": desc,
        "Rekommendation": advice,
        "Motivering": reason,
        "Streck (%)": f"{int(s1)}% - {int(sx)}% - {int(s2)}%",
        "TT (Tidningar)": f"{tt1} - {ttx} - {tt2}",
        "Värde 1": v1, "Värde X": vx, "Värde 2": v2
    })

df = pd.DataFrame(match_data)

# 2. Visa Assistentens Rekommendationer
st.subheader("🤖 Expertens Analys & Spelråd")
st.caption("Här vägs Tio Tidningars Tips (TT) samman med marknadsodds och streckfördelning.")

for idx, row in df.iterrows():
    with st.expander(f"Match {row['Nr']}: {row['Match']} — **{row['Rekommendation']}**"):
        st.write(f"**Motivering:** {row['Motivering']}")
        col_a, col_b = st.columns(2)
        col_a.write(f"📊 **Svenska folket (1-X-2):** {row['Streck (%)']}")
        col_b.write(f"📰 **Tio Tidningar (1-X-2):** {row['TT (Tidningar)']}")

st.divider()

# 3. Interaktiv Kupong & Reducering
st.subheader("📝 Bygg System & Reducera")

selections = []
for idx, row in df.iterrows():
    m_nr = row["Nr"]
    cols = st.columns([4, 1, 1, 1])
    cols[0].write(f"**{m_nr}. {row['Match']}**")
    
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
st.sidebar.header("⚙️ Reduceringsvillkor")
min_1, max_1 = st.sidebar.slider("Antal 1:or i systemet", 0, num_matches, (0, num_matches))
min_x, max_x = st.sidebar.slider("Antal X i systemet", 0, num_matches, (0, num_matches))
min_2, max_2 = st.sidebar.slider("Antal 2:or i systemet", 0, num_matches, (0, num_matches))

if all(len(s) > 0 for s in selections):
    all_rows = list(itertools.product(*selections))
    filtered_rows = [
        r for r in all_rows
        if (min_1 <= r.count("1") <= max_1)
        and (min_x <= r.count("X") <= max_x)
        and (min_2 <= r.count("2") <= max_2)
    ]
    
    st.info(f"**Matematiska rader:** {len(all_rows)} st ➡️ **Efter reducering:** {len(filtered_rows)} st (Kostnad: {len(filtered_rows)} kr)")
    
    if filtered_rows:
        lines = ["E"] + [",".join(r) for r in filtered_rows]
        file_content = "\n".join(lines)
        
        st.download_button(
            label="📥 Ladda ner systemfil (.txt) för Svenska Spel",
            data=file_content,
            file_name=f"{product}_omg_{draw.get('drawNumber')}.txt",
            mime="text/plain"
        )
else:
    st.warning("Du måste välja minst ett tecken i samtliga matcher.")
