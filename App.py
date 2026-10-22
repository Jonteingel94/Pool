import streamlit as st
import requests
import pandas as pd
import itertools
import re

st.set_page_config(page_title="Pool-Autopiloten Pro", layout="wide")
st.title("🏒 Pool-Autopiloten Pro – Powerplay Edition")
st.markdown("Automatisk research, Head-to-Head-detektor, utdelningsspärr och smart radrankning inom din budget!")

# --- 1. SIDOMENY: INSTÄLLNINGAR & BUDGET ---
product_map = {
    "Powerplay": "powerplay",
    "Stryktipset": "stryktipset",
    "Europatipset": "europatipset",
    "Topptipset": "topptipset"
}
selected_label = st.sidebar.selectbox("Välj spelform", list(product_map.keys()))
product = product_map[selected_label]

st.sidebar.divider()
st.sidebar.subheader("💰 1. Budget & Insats")
max_budget = st.sidebar.number_input("Max budget för kupongen (kr)", min_value=10, max_value=2000, value=50, step=10)
stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

st.sidebar.subheader("🧠 2. Strategi & Utdelningsspärr")
strategy = st.sidebar.selectbox(
    "Välj spelfilosofi",
    [
        "Balanserad (Smart mix av chans & värde)",
        "Säker (Favoritfokus / Högst chans till 8 rätt)",
        "Hög Utdelning / Jägaren (Maxat värde & skrällfokus)"
    ]
)

min_payout = st.sidebar.slider(
    "Minsta uppskattad utdelning (kr)", 
    min_value=0, max_value=2000, value=150, step=50,
    help="Rensar bort rader med för många storfavoriter som bara ger kaffepengar."
)

h2h_smart_mode = st.sidebar.checkbox(
    "🎯 Smart Head-to-Head-hantering", 
    value=True,
    help="Känner igen spelardueller (målskyttar) och låser/prioriterar X för att spara rader till lagmatcherna."
)

# --- 2. HÄMTA DATA FRÅN SVENSKA SPEL ---
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

def is_head_to_head(desc, sx, px):
    # Detekterar spelardueller genom initialer (t.ex. "M. Aagard") eller extremt hög kryssprocent (>36%)
    has_initials = bool(re.search(r"\b[A-ZÅÄÖ]\.\s?[A-ZÅÄÖa-zåäö]+", desc))
    high_draw_prob = (sx >= 36 or px >= 36)
    return has_initials or high_draw_prob

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

# --- 3. BEARBETA MATCHDATA ---
events = draw.get("drawEvents", [])
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    
    # Fallback om streckprocent saknas tidigt på dagen
    if s1 + sx + s2 == 0:
        s1, sx, s2 = 40.0, 20.0, 40.0
    
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

    # Spelvärde (Skillnad mellan äkta sannolikhet och folkets streck)
    v1 = round(p1 - s1, 1)
    vx = round(px - sx, 1)
    v2 = round(p2 - s2, 1)
    
    h2h = is_head_to_head(desc, sx, px) if product == "powerplay" else False
    
    match_data.append({
        "Nr": num, "Match": desc, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2,
        "p1": p1, "px": px, "p2": p2,
        "v1": v1, "vx": vx, "v2": v2,
        "tt1": tt1, "ttx": ttx, "tt2": tt2
    })

df = pd.DataFrame(match_data)

# --- 4. VALFRI MANUELL LÅSNING ("LÅS MIN SPIK") ---
manual_overrides = {}
with st.expander("🔒 Valfritt: Lås egna spikar eller tecken (Klicka för att öppna)"):
    st.caption("Om du har en egen idé i en specifik match kan du tvinga autopiloten att använda dina tecken där. Lämna på 'Auto' för att låta assistenten sköta allt.")
    for idx, row in df.iterrows():
        m_nr = row["Nr"]
        badge = " 🎯 [Spelarduell / H2H]" if row["H2H"] else ""
        choice = st.selectbox(
            f"{m_nr}. {row['Match']}{badge} (Folket: {int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2'])}%)",
            options=["🤖 Auto (Assistenten väljer)", "Spika 1", "Spika X", "Spika 2", "Halvgardera 1X", "Halvgardera X2", "Halvgardera 12", "Helgardera 1X2"],
            key=f"lock_{m_nr}"
        )
        if choice != "🤖 Auto (Assistenten väljer)":
            if "1X2" in choice: manual_overrides[m_nr] = ["1", "X", "2"]
            elif "1X" in choice: manual_overrides[m_nr] = ["1", "X"]
            elif "X2" in choice: manual_overrides[m_nr] = ["X", "2"]
            elif "12" in choice: manual_overrides[m_nr] = ["1", "2"]
            elif "1" in choice: manual_overrides[m_nr] = ["1"]
            elif "X" in choice: manual_overrides[m_nr] = ["X"]
            elif "2" in choice: manual_overrides[m_nr] = ["2"]

# --- 5. AUTOPILOTENS GRUNDURVAL PER MATCH ---
selections = []
match_explanations = []

for idx, row in df.iterrows():
    m_nr = row["Nr"]
    s1, sx, s2 = row["s1"], row["sx"], row["s2"]
    p1, px, p2 = row["p1"], row["px"], row["p2"]
    v1, vx, v2 = row["v1"], row["vx"], row["v2"]
    tt1, tt2 = row["tt1"], row["tt2"]
    is_h2h = row["H2H"]
    
    # 1. Kolla om användaren har låst matchen manuellt
    if m_nr in manual_overrides:
        signs = manual_overrides[m_nr]
        reason = "🔒 Manuellt låst av dig"
        
    # 2. Om det är en Head-to-Head (Spelarduell) och smart läge är på
    elif is_h2h and h2h_smart_mode:
        if strategy.startswith("Säker"):
            signs = ["X"]
            reason = "🎯 Spelarduell: Spikar X (0-0/lika är storfavorit, sparar rader!)"
        else:
            # Ta X + den spelare som har bäst spelvärde eller lägst odds
            best_wing = "1" if (p1 + v1) >= (p2 + v2) else "2"
            if max(p1, p2) >= 28 or max(v1, v2) >= 3:
                signs = sorted(["X", best_wing], key=lambda x: {"1":0, "X":1, "2":2}[x])
                reason = f"🎯 Spelarduell: Låser X + värdesidan ({best_wing}), sparar bort dyr helgardering"
            else:
                signs = ["X"]
                reason = "🎯 Spelarduell: Spikar X för att lägga krutet på lagmatcherna"
                
    # 3. Vanlig lagmatch - välj efter strategi
    else:
        signs = []
        if strategy.startswith("Säker"):
            # Stark favorit: spika!
            if p1 >= 55 or (s1 >= 60 and v1 >= -5):
                signs = ["1"]
                reason = "⚡ Stark hemmafavorit spikas"
            elif p2 >= 55 or (s2 >= 60 and v2 >= -5):
                signs = ["2"]
                reason = "⚡ Stark bortafavorit spikas"
            else:
                if p1 >= 30 or tt1 >= 5: signs.append("1")
                if px >= 23 or abs(p1 - p2) <= 12: signs.append("X")
                if p2 >= 30 or tt2 >= 5: signs.append("2")
                if not signs: signs = ["1", "2"]
                reason = "🛡️ Garderar jämn match mot mest sannolika tecken"
                
        elif strategy.startswith("Hög Utdelning"):
            # Om en storfavorit (>65%) är grovt överstreckad (v < -5), utelämna eller gardera!
            if s1 >= 65 and v1 <= -5:
                signs = ["1", "X", "2"] if p1 >= 58 else ["X", "2"]
                reason = "💣 Överstreckad storfavorit! Jagas med skrälltecken"
            elif s2 >= 65 and v2 <= -5:
                signs = ["1", "X", "2"] if p2 >= 58 else ["1", "X"]
                reason = "💣 Överstreckad bortafavorit! Jagas med skrälltecken"
            else:
                if v1 >= -2 or p1 >= 42: signs.append("1")
                if vx >= -2 or px >= 22: signs.append("X")
                if v2 >= -2 or p2 >= 42: signs.append("2")
                if len(signs) == 0: signs = ["1", "X", "2"]
                reason = "💎 Plockar tecken med högt spelvärde och renschans"
                
        else:  # Balanserad
            # Om vi har en sund favorit med bra odds och rimlig streckning -> Värdespik!
            if p1 >= 52 and v1 >= -3:
                signs = ["1"]
                reason = "✅ Sund favorit (bra odds mot streck) – spikas!"
            elif p2 >= 52 and v2 >= -3:
                signs = ["2"]
                reason = "✅ Sund bortafavorit – spikas!"
            else:
                if p1 >= 32 or v1 >= 2 or tt1 >= 5: signs.append("1")
                if px >= 21 or vx >= 2 or abs(s1 - s2) <= 15: signs.append("X")
                if p2 >= 32 or v2 >= 2 or tt2 >= 5: signs.append("2")
                if not signs: signs = ["1", "X", "2"]
                reason = "⚖️ Balanserad gardering utifrån odds och spelvärde"

    selections.append(signs)
    match_explanations.append(reason)

# --- 6. SMART RADMOTORN (POÄNGSÄTTNING, BALANS & UTDELNINGSSPÄRR) ---
all_rows = list(itertools.product(*selections))
allowed_max_rows = int(max_budget / stake_per_row)

def evaluate_row(r):
    prob_Map = {"1": "p1", "X": "px", "2": "p2"}
    folket_Map = {"1": "s1", "X": "sx", "2": "s2"}
    val_Map = {"1": "v1", "X": "vx", "2": "v2"}
    
    folket_prod = 1.0
    prob_sum = 0.0
    value_sum = 0.0
    underdogs = 0
    favorites = 0
    
    for i, sign in enumerate(r):
        m = match_data[i]
        s_pct = max(m[folket_Map[sign]], 1.0) / 100.0
        p_pct = max(m[prob_Map[sign]], 1.0)
        v_pts = m[val_Map[sign]]
        
        folket_prod *= s_pct
        prob_sum += p_pct
        value_sum += v_pts
        
        # Räkna hur många tunga favoriter respektive skrällar raden har (i vanliga lagmatcher)
        if not m["H2H"]:
            if m[folket_Map[sign]] >= 50:
                favorites += 1
            elif m[folket_Map[sign]] <= 22:
                underdogs += 1

    # Uppskattad teoretisk utdelning vid 8 rätt (70% återbetalning i poolen)
    est_payout = round((0.70 / folket_prod) * stake_per_row)
    
    # Balans-straff: Undvik rader med 8 osannolika megaskrällar samtidigt
    balance_bonus = 0
    if strategy.startswith("Balanserad"):
        if 1 <= underdogs <= 3 and favorites >= 2:
            balance_bonus = 40  # Perfekt mix för en vinnande kupong!
        elif underdogs >= 5:
            balance_bonus = -100 # Alldeles för orealistisk rad
        score = (prob_sum * 0.65) + (value_sum * 1.6) + balance_bonus
        
    elif strategy.startswith("Säker"):
        score = (prob_sum * 1.2) + (value_sum * 0.4)
        
    else: # Hög Utdelning / Jägaren
        if 2 <= underdogs <= 4:
            balance_bonus = 50
        elif underdogs >= 6:
            balance_bonus = -80 # Även Jägaren måste ha realistisk chans att sitta
        score = (prob_sum * 0.45) + (value_sum * 2.2) + balance_bonus
        
    return score, est_payout, underdogs

evaluated = []
for r in all_rows:
    score, payout, dogs = evaluate_row(r)
    evaluated.append({"row": r, "score": score, "payout": payout, "dogs": dogs})

# 1. Filtrera med utdelningsspärren (slipp kaffepengar)
payout_filtered = [item for item in evaluated if item["payout"] >= min_payout]

# Om spärren var för hård (t.ex. om man låst många favoriter), behåll de rader som ger högst utdelning
if len(payout_filtered) < allowed_max_rows and len(evaluated) > 0:
    evaluated.sort(key=lambda x: x["payout"], reverse=True)
    payout_filtered = evaluated[:max(allowed_max_rows * 2, len(evaluated))]

# 2. Sortera efter vår kombinerade Värde + Sannolikhetspoäng
payout_filtered.sort(key=lambda x: x["score"], reverse=True)

# 3. Plocka ut de absolut skarpaste raderna inom din budget
selected_items = payout_filtered[:allowed_max_rows]
filtered_rows = [item["row"] for item in selected_items]

# --- 7. PRESENTATION & NEDLADDNING ---
st.subheader("🎯 Autopilotens Färdiga Spelplan")

if selected_items:
    avg_payout = int(sum(x["payout"] for x in selected_items) / len(selected_items))
    min_p = min(x["payout"] for x in selected_items)
    max_p = max(x["payout"] for x in selected_items)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Antal skarpa rader", f"{len(filtered_rows)} st", f"Maxbudget: {max_budget} kr")
    col2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"{stake_per_row} kr / rad")
    col3.metric("Uppskattat utdelningsspann", f"{min_p} – {max_p:,} kr".replace(",", " "), f"Snitt: ~{avg_payout:,} kr".replace(",", " "))

st.info(f"✨ Från **{len(all_rows)}** möjliga grundkombinationer har motorn sållat bort rader med för låg utdelning och handplockat de **{len(filtered_rows)} starkaste raderna** med bäst balans mellan vinstchans och spelvärde.")

with st.expander("🔍 Se autopilotens analys, H2H-detektor och val per match", expanded=True):
    table_rows = []
    for idx, row in df.iterrows():
        m_type = "🎯 Spelarduell" if row["H2H"] else "🏒 Lagmatch"
        table_rows.append({
            "Match": f"{row['Nr']}. {row['Match']}",
            "Typ": m_type,
            "Folket (1-X-2)": f"{int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2'])}%",
            "Odds-chans": f"{int(row['p1'])}% - {int(row['px'])}% - {int(row['p2'])}%",
            "Valda tecken": ", ".join(selections[idx]),
            "Autopilotens kommentar": match_explanations[idx]
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

st.divider()

if filtered_rows:
    header_line = f"{selected_label},Omg={draw_number},Insats={stake_per_row}"
    lines = [header_line] + [f"E," + ",".join(r) for r in filtered_rows]
    file_content = "\n".join(lines)
    
    st.download_button(
        label=f"📥 Ladda ner färdig systemfil ({len(filtered_rows) * stake_per_row} kr) för Svenska Spel",
        data=file_content,
        file_name=f"{product}_omg_{draw_number}.txt",
        mime="text/plain",
        type="primary"
    )
else:
    st.warning("Kunde inte generera några rader. Prova att sänka utdelningsspärren eller höja budgeten.")
