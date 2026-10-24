import streamlit as st
import requests
import pandas as pd
import itertools
import random
import re

st.set_page_config(page_title="Pool-Autopiloten AI Pro", layout="wide")
st.title("🏆 Pool-Autopiloten AI Pro – Stryktipset & Powerplay")
st.markdown("Kombinerar marknadsodds, Svenska Spels dolda rankingdata, AI-Edge och smart radspridning (Anti-klump-filter) inom din budget!")

# --- 1. SIDOMENY: INSTÄLLNINGAR & BUDGET ---
product_map = {
    "Stryktipset (13 matcher)": "stryktipset",
    "Europatipset (13 matcher)": "europatipset",
    "Topptipset (8 matcher)": "topptipset",
    "Powerplay (8 matcher)": "powerplay"
}
selected_label = st.sidebar.selectbox("Välj spelform", list(product_map.keys()))
product = product_map[selected_label]
Export_Name = selected_label.split(" ")[0] # T.ex. "Stryktipset" eller "Powerplay"

st.sidebar.divider()
st.sidebar.subheader("💰 1. Budget & Insats")
max_budget = st.sidebar.number_input("Max budget för kupongen (kr)", min_value=10, max_value=3000, value=100, step=10)
if product == "stryktipset" or product == "europatipset":
    stake_per_row = 1 # Stryktipset/Europatipset har alltid 1 kr radpris
    st.sidebar.caption("ℹ️ Radinsats på Stryktipset/Europatipset är alltid 1 kr/rad.")
else:
    stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

st.sidebar.subheader("🧠 2. AI-Strategi & Filter")
strategy = st.sidebar.selectbox(
    "Välj spelfilosofi",
    [
        "Balanserad (Optimal mix av AI-Edge & vinstchans)",
        "Säker (Favorit- & Formfokus / Flest rätt)",
        "Hög Utdelning / Jägaren (Maxad AI-Edge & skrälljakt)"
    ]
)

default_min_payout = 1000 if product in ["stryktipset", "europatipset"] else 150
max_slider_payout = 50000 if product in ["stryktipset", "europatipset"] else 2000
step_slider = 500 if product in ["stryktipset", "europatipset"] else 50

min_payout = st.sidebar.slider(
    "Minsta uppskattad utdelning vid alla rätt (kr)", 
    min_value=0, max_value=max_slider_payout, value=default_min_payout, step=step_slider,
    help="Rensar bort 'kaffepengsrader' där alldeles för många storfavoriter vinner samtidigt."
)

min_hamming = st.sidebar.slider(
    "🛡️ Radspridning (Minsta antal tecken som måste skilja)", 
    min_value=1, max_value=4, value=2 if product in ["stryktipset", "europatipset"] else 1,
    help="Anti-klump-filter! Om du väljer 2 måste varje utvald rad skilja sig på minst 2 matcher från dina övriga rader. Ger betydligt bredare täckning till 10-13 rätt!"
)

h2h_smart_mode = False
if product == "powerplay":
    h2h_smart_mode = st.sidebar.checkbox(
        "🎯 Smart Head-to-Head-hantering (Powerplay)", 
        value=True,
        help="Känner igen spelardueller och låser/prioriterar X för att spara rader till lagmatcherna."
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
    has_initials = bool(re.search(r"\b[A-ZÅÄÖ]\.\s?[A-ZÅÄÖa-zåäö]+", desc))
    high_draw_prob = (sx >= 36 or px >= 36)
    return has_initials or high_draw_prob

def extract_team_rankings(ev):
    """Försöker hämta tabellplacering eller ranking ur Svenska Spels dolda API-fält."""
    home_rank, away_rank = None, None
    try:
        match_obj = ev.get("match", {})
        for p in match_obj.get("participants", []):
            t_type = p.get("type", "").lower()
            rank = p.get("ranking") or p.get("tablePosition")
            if rank:
                if "home" in t_type: home_rank = int(rank)
                elif "away" in t_type: away_rank = int(rank)
    except Exception:
        pass
    return home_rank, away_rank

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

# --- 3. BEARBETA MATCHDATA & BERÄKNA AI-EDGE ---
events = draw.get("drawEvents", [])
num_matches = len(events)
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    
    if s1 + sx + s2 == 0:
        s1, sx, s2 = 40.0, 25.0, 35.0
    
    tt = ev.get("tioTidningarsTips") or {}
    tt1 = int(tt.get("one", 0) or 0)
    ttx = int(tt.get("x", 0) or 0)
    tt2 = int(tt.get("two", 0) or 0)
    tt_sum = max(tt1 + ttx + tt2, 1)
    
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

    # --- SPORTS-AI-BETTOR LOGIK: KOMBINERAD AI-SANNOLIKHET (Odds + Expert-TT + Tabellranking) ---
    h_rank, a_rank = extract_team_rankings(ev)
    rank_bonus_1, rank_bonus_2 = 0.0, 0.0
    rank_info = ""
    if h_rank and a_rank:
        rank_diff = a_rank - h_rank # Positiv om hemmalaget ligger högre i tabellen
        rank_bonus_1 = max(min(rank_diff * 0.25, 3.5), -3.5)
        rank_bonus_2 = -rank_bonus_1
        rank_info = f" (Tabell: #{h_rank} vs #{a_rank})"

    # Väg in Tio Tidningars Tips (om tillgängligt) och tabellstyrka i AI-modellen
    if (tt1 + ttx + tt2) > 0:
        ai_p1 = (p1 * 0.88) + ((tt1 / tt_sum) * 100 * 0.12) + rank_bonus_1
        ai_px = (px * 0.90) + ((ttx / tt_sum) * 100 * 0.10)
        ai_p2 = (p2 * 0.88) + ((tt2 / tt_sum) * 100 * 0.12) + rank_bonus_2
    else:
        ai_p1, ai_px, ai_p2 = p1 + rank_bonus_1, px, p2 + rank_bonus_2

    # Normalisera AI-sannolikheten till exakt 100%
    ai_tot = max(ai_p1 + ai_px + ai_p2, 1.0)
    ai_p1 = round((max(ai_p1, 1.0) / ai_tot) * 100, 1)
    ai_px = round((max(ai_px, 1.0) / ai_tot) * 100, 1)
    ai_p2 = round((max(ai_p2, 1.0) / ai_tot) * 100, 1)

    # AI-Edge (Skillnad mellan AI-modellens sannolikhet och Svenska Folkets streck)
    v1 = round(ai_p1 - s1, 1)
    vx = round(ai_px - sx, 1)
    v2 = round(ai_p2 - s2, 1)
    
    h2h = is_head_to_head(desc, sx, px) if product == "powerplay" else False
    
    match_data.append({
        "Nr": num, "Match": desc + rank_info, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2,
        "p1": ai_p1, "px": ai_px, "p2": ai_p2,
        "v1": v1, "vx": vx, "v2": v2,
        "tt1": tt1, "ttx": ttx, "tt2": tt2
    })

df = pd.DataFrame(match_data)

# --- 4. VALFRI MANUELL LÅSNING ("LÅS MIN SPIK") ---
manual_overrides = {}
with st.expander("🔒 Valfritt: Lås egna spikar eller garderingar (Klicka för att öppna)"):
    st.caption("Vill du spika ditt favoritlag på Stryktipset? Välj här så rättar sig AI-motorn efter dig!")
    for idx, row in df.iterrows():
        m_nr = row["Nr"]
        badge = " 🎯 [H2H]" if row["H2H"] else ""
        choice = st.selectbox(
            f"{m_nr}. {row['Match']}{badge} | Folket: {int(row['s1'])}%-{int(row['sx'])}%-{int(row['s2'])}% | AI: {int(row['p1'])}%-{int(row['px'])}%-{int(row['p2'])}%",
            options=["🤖 Auto (AI väljer)", "Spika 1", "Spika X", "Spika 2", "Halvgardera 1X", "Halvgardera X2", "Halvgardera 12", "Helgardera 1X2"],
            key=f"lock_{product}_{draw_number}_{m_nr}"
        )
        if choice != "🤖 Auto (AI väljer)":
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
    
    if m_nr in manual_overrides:
        signs = manual_overrides[m_nr]
        reason = "🔒 Manuellt låst av dig"
        
    elif is_h2h and h2h_smart_mode:
        if strategy.startswith("Säker"):
            signs = ["X"]
            reason = "🎯 Spelarduell: Spikar X (sparar rader!)"
        else:
            best_wing = "1" if (p1 + v1) >= (p2 + v2) else "2"
            if max(p1, p2) >= 28 or max(v1, v2) >= 3:
                signs = sorted(["X", best_wing], key=lambda x: {"1":0, "X":1, "2":2}[x])
                reason = f"🎯 Spelarduell: Låser X + värdesidan ({best_wing})"
            else:
                signs = ["X"]
                reason = "🎯 Spelarduell: Spikar X"
                
    else:
        signs = []
        if strategy.startswith("Säker"):
            if p1 >= 54 or (s1 >= 60 and v1 >= -5):
                signs = ["1"]
                reason = "⚡ Stark hemmafavorit spikas"
            elif p2 >= 54 or (s2 >= 60 and v2 >= -5):
                signs = ["2"]
                reason = "⚡ Stark bortafavorit spikas"
            else:
                if p1 >= 30 or tt1 >= 5: signs.append("1")
                if px >= 25 or abs(p1 - p2) <= 14: signs.append("X")
                if p2 >= 30 or tt2 >= 5: signs.append("2")
                if not signs: signs = ["1", "X"] if p1 >= p2 else ["X", "2"]
                reason = "🛡️ Garderar jämn match"
                
        elif strategy.startswith("Hög Utdelning"):
            # Fäll grovt överstreckade storfavoriter eller helgardera dem
            if s1 >= 62 and v1 <= -5:
                signs = ["1", "X", "2"] if p1 >= 56 else ["X", "2"]
                reason = f"💣 Överstreckad favorit ({int(s1)}%)! Jagas med skräll"
            elif s2 >= 62 and v2 <= -5:
                signs = ["1", "X", "2"] if p2 >= 56 else ["1", "X"]
                reason = f"💣 Överstreckad bortafavorit ({int(s2)}%)! Jagas med skräll"
            # Om vi hittar en grym värdespik (hög AI-chans + positiv Edge)
            elif p1 >= 48 and v1 >= 4:
                signs = ["1"]
                reason = f"💎 Omgångens AI-Värdespik! (+{v1}% Edge)"
            elif p2 >= 48 and v2 >= 4:
                signs = ["2"]
                reason = f"💎 Omgångens AI-Värdespik! (+{v2}% Edge)"
            else:
                if v1 >= -2 or p1 >= 42: signs.append("1")
                if vx >= -2 or px >= 24: signs.append("X")
                if v2 >= -2 or p2 >= 42: signs.append("2")
                if not signs: signs = ["1", "X", "2"]
                reason = "🔥 Plockar tecken med hög AI-Edge"
                
        else:  # Balanserad
            if p1 >= 50 and v1 >= -2:
                signs = ["1"]
                reason = f"✅ Sund AI-spik (AI: {int(p1)}%, Edge: {v1:+}%)"
            elif p2 >= 50 and v2 >= -2:
                signs = ["2"]
                reason = f"✅ Sund AI-spik (AI: {int(p2)}%, Edge: {v2:+}%)"
            else:
                if p1 >= 32 or v1 >= 2.5 or tt1 >= 5: signs.append("1")
                if px >= 24 or vx >= 2.5 or abs(p1 - p2) <= 14: signs.append("X")
                if p2 >= 32 or v2 >= 2.5 or tt2 >= 5: signs.append("2")
                if not signs: signs = ["1", "X", "2"]
                reason = "⚖️ Balanserad gardering (AI-chans + Edge)"

    selections.append(signs)
    match_explanations.append(reason)

# --- 6. STRYKTIPS-SÄKER RADMOTOR (KLARAR MILJONTALS KOMBINATIONER) ---
allowed_max_rows = int(max_budget / stake_per_row)

# Räkna ut hur många matematiska rader grundvalen ger
total_combinations = 1
for s in selections:
    total_combinations *= len(s)

MAX_EXACT_ROWS = 25000  # Gräns för att appen alltid ska svara blixtsnabbt

if total_combinations <= MAX_EXACT_ROWS:
    candidate_rows = list(itertools.product(*selections))
else:
    # Smart viktad Monte Carlo-sampling när 13 matcher ger 50 000 - 1 500 000 rader!
    random.seed(draw_number + int(max_budget) + len(strategy))
    sampled_set = set()
    
    # Beräkna vikter per match och tecken så att vi drar högkvalitativa kandidater
    match_weights = []
    for i, signs in enumerate(selections):
        m = match_data[i]
        w = []
        for s in signs:
            prob = m[f"p{s.lower()}"]
            edge = m[f"v{s.lower()}"]
            if strategy.startswith("Säker"):
                weight = max(prob, 5.0)
            elif strategy.startswith("Hög Utdelning"):
                weight = max(prob + (edge * 2.2), 5.0)
            else:
                weight = max(prob + (edge * 1.4), 5.0)
            w.append(weight)
        match_weights.append(w)
        
    attempts = 0
    target_samples = 18000
    while len(sampled_set) < target_samples and attempts < target_samples * 3:
        attempts += 1
        row_list = [random.choices(selections[i], weights=match_weights[i], k=1)[0] for i in range(num_matches)]
        sampled_set.add(tuple(row_list))
    candidate_rows = list(sampled_set)

def evaluate_row(r):
    prob_Map = {"1": "p1", "X": "px", "2": "p2"}
    folket_Map = {"1": "s1", "X": "sx", "2": "s2"}
    val_Map = {"1": "v1", "X": "vx", "2": "v2"}
    
    folket_prod = 1.0
    prob_sum = 0.0
    value_sum = 0.0
    underdogs = 0
    favorites = 0
    draws_count = 0
    
    for i, sign in enumerate(r):
        m = match_data[i]
        s_pct = max(m[folket_Map[sign]], 1.0) / 100.0
        p_pct = max(m[prob_Map[sign]], 1.0)
        v_pts = m[val_Map[sign]]
        
        folket_prod *= s_pct
        prob_sum += p_pct
        value_sum += v_pts
        
        if sign == "X":
            draws_count += 1
        if not m["H2H"]:
            if m[folket_Map[sign]] >= 50:
                favorites += 1
            elif m[folket_Map[sign]] <= 22:
                underdogs += 1

    # Uppskattad utdelning vid alla rätt (8 rätt på PP vs 13 rätt på Stryktipset)
    pool_share = 0.28 if num_matches == 13 else 0.70
    est_payout = round((pool_share / folket_prod) * stake_per_row)
    
    # Dynamisk balansbonus (anpassad efter 8 eller 13 matcher)
    balance_bonus = 0
    ideal_dogs_min = 2 if num_matches == 13 else 1
    ideal_dogs_max = 5 if num_matches == 13 else 3
    too_many_dogs = 7 if num_matches == 13 else 5
    
    # På 13 matcher i fotboll brukar det bli 2 till 5 kryss
    if num_matches == 13 and (draws_count == 0 or draws_count >= 7):
        balance_bonus -= 50

    if strategy.startswith("Balanserad"):
        if ideal_dogs_min <= underdogs <= ideal_dogs_max and favorites >= (3 if num_matches == 13 else 2):
            balance_bonus += 45
        elif underdogs >= too_many_dogs:
            balance_bonus -= 120
        score = (prob_sum * 0.65) + (value_sum * 1.65) + balance_bonus
        
    elif strategy.startswith("Säker"):
        score = (prob_sum * 1.25) + (value_sum * 0.45) + balance_bonus
        
    else: # Hög Utdelning / Jägaren
        if (ideal_dogs_min + 1) <= underdogs <= (ideal_dogs_max + 1):
            balance_bonus += 55
        elif underdogs >= (too_many_dogs + 1):
            balance_bonus -= 100
        score = (prob_sum * 0.45) + (value_sum * 2.25) + balance_bonus
        
    return score, est_payout, underdogs

evaluated = []
for r in candidate_rows:
    score, payout, dogs = evaluate_row(r)
    evaluated.append({"row": r, "score": score, "payout": payout, "dogs": dogs})

# 1. Filtrera med utdelningsspärren
payout_filtered = [item for item in evaluated if item["payout"] >= min_payout]
if len(payout_filtered) < allowed_max_rows and len(evaluated) > 0:
    evaluated.sort(key=lambda x: x["payout"], reverse=True)
    payout_filtered = evaluated[:max(allowed_max_rows * 3, len(evaluated))]

# 2. Sortera efter vår kombinerade AI-Score
payout_filtered.sort(key=lambda x: x["score"], reverse=True)

# 3. ANTI-KLUMP-FILTER (Hamming-avstånd för optimal radspridning!)
def hamming_distance(r1, r2):
    return sum(c1 != c2 for c1, c2 in zip(r1, r2))

selected_items = []
if min_hamming <= 1:
    selected_items = payout_filtered[:allowed_max_rows]
else:
    for item in payout_filtered:
        if len(selected_items) >= allowed_max_rows:
            break
        r = item["row"]
        if all(hamming_distance(r, sel["row"]) >= min_hamming for sel in selected_items):
            selected_items.append(item)
            
    # Om filtret var så hårt att vi inte fyllde budgeten, fyll på med näst bästa rader
    if len(selected_items) < allowed_max_rows:
        chosen_set = {x["row"] for x in selected_items}
        for item in payout_filtered:
            if len(selected_items) >= allowed_max_rows:
                break
            if item["row"] not in chosen_set:
                selected_items.append(item)
                chosen_set.add(item["row"])

filtered_rows = [item["row"] for item in selected_items]

# --- 7. PRESENTATION & NEDLADDNING ---
st.subheader(f"🎯 Autopilotens Färdiga Spelplan ({Export_Name})")

if selected_items:
    avg_payout = int(sum(x["payout"] for x in selected_items) / len(selected_items))
    min_p = min(x["payout"] for x in selected_items)
    max_p = max(x["payout"] for x in selected_items)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Antal AI-optimerade rader", f"{len(filtered_rows)} st", f"Budget: {max_budget} kr")
    col2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"Radspridning: minst {min_hamming} tecken")
    col3.metric(f"Uppskattad vinst ({num_matches} rätt)", f"{min_p:,} – {max_p:,} kr".replace(",", " "), f"Snitt: ~{avg_payout:,} kr".replace(",", " "))

st.info(
    f"✨ Från **{total_combinations:,}** möjliga grundkombinationer har AI-motorn vägt samman odds, TT och tabellstyrka, "
    f"sållat bort lågutdelande rader och spridit ut de **{len(filtered_rows)} skarpaste raderna** över kupongen.".replace(",", " ")
)

with st.expander("🔍 Se AI-analys, Edge (övervärde) och valda tecken per match", expanded=True):
    table_rows = []
    for idx, row in df.iterrows():
        # Hitta bäst Edge i matchen
        edges = {"1": row["v1"], "X": row["vx"], "2": row["v2"]}
        best_sign = max(edges, key=edges.get)
        best_edge = edges[best_sign]
        edge_str = f"{best_sign} ({best_edge:+}%)" if best_edge > 0 else "Ingen tydlig"
        
        table_rows.append({
            "Match": f"{row['Nr']}. {row['Match']}",
            "Folket (1-X-2)": f"{int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2'])}%",
            "AI-Modell (1-X-2)": f"{int(row['p1'])}% - {int(row['px'])}% - {int(row['p2'])}%",
            "Bästa AI-Edge": edge_str,
            "Valda tecken": ", ".join(selections[idx]),
            "AI-Kommentar": match_explanations[idx]
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

st.divider()

if filtered_rows:
    # Svenska Spels externa systemfilsformat:
    # Stryktipset/Europatipset ska INTE ha ",Insats=1" i headern, medan Powerplay/Topptipset har det.
    if product in ["stryktipset", "europatipset"]:
        header_line = f"{Export_Name},Omg={draw_number}"
    else:
        header_line = f"{Export_Name},Omg={draw_number},Insats={stake_per_row}"
        
    lines = [header_line] + [f"E," + ",".join(r) for r in filtered_rows]
    file_content = "\n".join(lines)
    
    st.download_button(
        label=f"📥 Ladda ner färdig systemfil ({len(filtered_rows) * stake_per_row} kr) för {Export_Name}",
        data=file_content,
        file_name=f"{product}_omg_{draw_number}.txt",
        mime="text/plain",
        type="primary"
    )
else:
    st.warning("Kunde inte generera några rader. Prova att sänka utdelningsspärren i sidomenyn.")
