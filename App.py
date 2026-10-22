import streamlit as st
import requests
import pandas as pd
import itertools

st.set_page_config(page_title="Pool-Autopiloten", layout="wide")
st.title("🤖 Intelligent Pool-Autopilot")
st.markdown("Sätt din budget och strategi – assistenten analyserar oddsen, poängsätter alla rader och handplockar de bästa inom din budget!")

# 1. Välj spel i sidomenyn
product_map = {
    "Powerplay": "powerplay",
    "Stryktipset": "stryktipset",
    "Europatipset": "europatipset",
    "Topptipset": "topptipset"
}
selected_label = st.sidebar.selectbox("Välj spelform", list(product_map.keys()))
product = product_map[selected_label]

st.sidebar.divider()
st.sidebar.subheader("💰 Budget & Strategi")
max_budget = st.sidebar.number_input("Max budget för kupongen (kr)", min_value=20, max_value=1000, value=50, step=10)
stake_per_row = st.sidebar.selectbox("Insats per rad", [1, 2, 5, 10], index=0)

strategy = st.sidebar.selectbox(
    "Välj spelfilosofi",
    [
        "Balanserad (Blandat värde & trygghet)",
        "Säker (Favoritfokus / Flest rätt)",
        "Hög Utdelning / Jägaren (Fångar skrällar & rensar)"
    ]
)

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

# --- AUTOPILOTENS LOGIK & VÄRDERANKNING ---
selections = []
for idx, row in df.iterrows():
    s1, sx, s2 = row["s1"], row["sx"], row["s2"]
    v1, v2 = row["v1"], row["v2"]
    tt1, tt2 = row["tt1"], row["tt2"]
    
    signs = []
    if strategy == "Säker (Favoritfokus / Flest rätt)":
        if s1 >= max(s1, sx, s2) or tt1 >= 6: signs.append("1")
        if sx >= 30: signs.append("X")
        if s2 >= max(s1, sx, s2) or tt2 >= 6: signs.append("2")
        if not signs: signs = ["1"]
        
    elif strategy == "Hög Utdelning / Jägaren (Fångar skrällar & rensar)":
        if v1 >= 0 or s1 < 50: signs.append("1")
        signs.append("X")
        if v2 >= 0 or s2 < 50: signs.append("2")
        
    else:  # Balanserad
        if v1 >= -3 or tt1 >= 5: signs.append("1")
        if sx >= 22 or v2 >= 2: signs.append("X")
        if v2 >= -3 or tt2 >= 5: signs.append("2")
        if not signs: signs = ["1", "X"]

    selections.append(signs)

# Skapa alla matematiska kombinationer
all_rows = list(itertools.product(*selections))
allowed_max_rows = int(max_budget / stake_per_row)

# INTELLIGENT URVAL: Poängsätt varje rad baserat på spelvärde
scored_rows = []
for r in all_rows:
    row_score = 0
    for i, sign in enumerate(r):
        m = match_data[i]
        if sign == "1":
            row_score += m["v1"]
        elif sign == "X":
            row_score += m["vx"]
        elif sign == "2":
            row_score += m["v2"]
    scored_rows.append((row_score, r))

# Sortera efter högst spelvärde/poäng
scored_rows.sort(key=lambda x: x[0], reverse=True)

# Plocka ut de bästa raderna upp till tillåten maxbudget
best_rows = [r for score, r in scored_rows]
filtered_rows = best_rows[:allowed_max_rows]

# 2. Huvudfönster
st.subheader("🎯 Autopilotens Smart Handplockade Rader")
st.write(f"**Vald strategi:** {strategy}")
st.write(f"**Max budget:** {max_budget} kr (Insats: {stake_per_row} kr/rad)")
st.info(f"✨ Appen har analyserat alla kombinationer, viktat in odds och handplockat de **{len(filtered_rows)} bästa raderna** (Total kostnad: {len(filtered_rows) * stake_per_row} kr).")

with st.expander("🔍 Se autopilotens valda tecken per match"):
    for idx, row in df.iterrows():
        st.write(f"**{row['Nr']}. {row['Match']}** | Folket: {int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2'])}% | Tecken: `{', '.join(selections[idx])}`")

st.divider()

# 3. Nedladdning
if filtered_rows:
    header_line = f"{selected_label},Omg={draw_number},Insats={stake_per_row}"
    lines = [header_line] + [f"E," + ",".join(r) for r in filtered_rows]
    file_content = "\n".join(lines)
    
    st.download_button(
        label="📥 Ladda ner färdig systemfil (.txt) för Svenska Spel",
        data=file_content,
        file_name=f"{product}_omg_{draw_number}.txt",
        mime="text/plain",
        type="primary"
    )
else:
    st.warning("Kunde inte generera rader. Prova att justera inställningarna.")
