import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
import re

st.set_page_config(page_title="AI Pool-Autopilot Ultra", layout="wide")
st.title("🤖 Helautomatisk AI-Autopilot – All Statistik Inbakad")
st.markdown("100 % automatisk analys av **Marknadsodds, Streckvärde, Tabell, Formkurva, Experttips (TT) & Målförväntan**. Sätt bara din budget och ladda ner!")

# --- 1. SIDOMENY: ENDAST BUDGET & SPELFORM ---
product_map = {
    "Stryktipset (13 matcher)": "stryktipset",
    "Europatipset (13 matcher)": "europatipset",
    "Topptipset (8 matcher)": "topptipset",
    "Powerplay (8 matcher)": "powerplay"
}
selected_label = st.sidebar.selectbox("1. Välj spelform", list(product_map.keys()))
product = product_map[selected_label]
Export_Name = selected_label.split(" ")[0]

st.sidebar.divider()
st.sidebar.subheader("💰 2. Din Budget")
max_budget = st.sidebar.number_input("Total budget för kupongen (kr)", min_value=10, max_value=5000, value=200, step=10)

if product in ["stryktipset", "europatipset"]:
    stake_per_row = 1
    st.sidebar.caption("ℹ️ Radinsats på Stryktipset/Europatipset är 1 kr/rad.")
else:
    stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

st.sidebar.subheader("⚙️ 3. Autopilot-profil")
strategy = st.sidebar.selectbox(
    "Välj riskprofil",
    [
        "Helautomatisk Optimal (Maximerar EV: Chans x Utdelning)",
        "Jobbtävlings-Jägaren (Mer vikt på skrällar & hög utdelning)",
        "Trygg & Formstark (Fokus på flest rätt & starkaste lagen)"
    ]
)

# --- 2. HÄMTA ALL DATA FRÅN SVENSKA SPEL ---
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

def extract_deep_stats(ev):
    """Dammsuger API-svaret på tabellplacering, form (senaste matcher) och statistik."""
    h_rank, a_rank = None, None
    h_form_pts, a_form_pts = 0.0, 0.0
    stat_summary = []

    try:
        match_obj = ev.get("match", {})
        for p in match_obj.get("participants", []):
            t_type = p.get("type", "").lower()
            rank = p.get("ranking") or p.get("tablePosition")
            
            # Beräkna formpoäng om form-sträng/lista finns (t.ex. W, D, L / V, O, F)
            form_raw = p.get("form") or p.get("trend") or ""
            f_pts = 0
            if isinstance(form_raw, str) and form_raw:
                for ch in form_raw.upper()[-5:]:
                    if ch in ["W", "V", "3"]: f_pts += 3
                    elif ch in ["D", "O", "X", "1"]: f_pts += 1
            elif isinstance(form_raw, list):
                for item in form_raw[-5:]:
                    res = str(item).upper()
                    if "W" in res or "V" in res: f_pts += 3
                    elif "D" in res or "O" in res: f_pts += 1

            if "home" in t_type:
                if rank: h_rank = int(rank)
                h_form_pts = f_pts
            elif "away" in t_type:
                if rank: a_rank = int(rank)
                a_form_pts = f_pts

        # Kolla även providerIds / match-status / kommentar
        if h_rank and a_rank:
            stat_summary.append(f"Tabell: #{h_rank} vs #{a_rank}")
        if h_form_pts > 0 or a_form_pts > 0:
            stat_summary.append(f"Form(5): {h_form_pts}p vs {a_form_pts}p")
    except Exception:
        pass

    return h_rank, a_rank, h_form_pts, a_form_pts, " | ".join(stat_summary)

draws = fetch_draws(product)

if not draws:
    st.warning("Ingen öppen omgång hittades just nu för detta spel.")
    st.stop()

draw_options = {f"Omgång {d.get('drawNumber')} - {d.get('drawComment', '')}": d for d in draws}
selected_draw_key = st.sidebar.selectbox("Välj omgång", list(draw_options.keys()))
draw = draw_options[selected_draw_key]
draw_number = draw.get('drawNumber')

if st.sidebar.button("🔄 Uppdatera all live-statistik"):
    st.cache_data.clear()
    st.rerun()

# --- 3. HELAUTOMATISK STATISTIKMOTOR (ODDS + FORM + TABELL + TT + POISSON-KRYSS) ---
events = draw.get("drawEvents", [])
num_matches = len(events)
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    
    # 1. Svenska Folket (Streckfördelning)
    sf = ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    if s1 + sx + s2 == 0:
        s1, sx, s2 = 40.0, 26.0, 34.0
    
    # 2. Tio Tidningars Tips (Experter)
    tt = ev.get("tioTidningarsTips") or {}
    tt1 = int(tt.get("one", 0) or 0)
    ttx = int(tt.get("x", 0) or 0)
    tt2 = int(tt.get("two", 0) or 0)
    tt_sum = tt1 + ttx + tt2
    
    # 3. Marknadsodds (Grundsannolikhet justerad för spelbolagets marginal)
    odds = ev.get("odds") or {}
    o1 = parse_odd(odds.get("one"))
    ox = parse_odd(odds.get("x"))
    o2 = parse_odd(odds.get("two"))
    
    if o1 > 0 and ox > 0 and o2 > 0:
        # Power-metod för att ta bort bookmakerns "overround" (mer exakt än enkel division)
        inv1, invx, inv2 = (1/o1)**1.05, (1/ox)**1.05, (1/o2)**1.05
        total_inv = inv1 + invx + inv2
        odd_p1 = (inv1 / total_inv) * 100
        odd_px = (invx / total_inv) * 100
        odd_p2 = (inv2 / total_inv) * 100
    else:
        odd_p1, odd_px, odd_p2 = s1, sx, s2

    # 4. Djupstatistik: Tabell & Form
    h_rank, a_rank, h_form, a_form, stat_str = extract_deep_stats(ev)
    
    stat_adj_1, stat_adj_x, stat_adj_2 = 0.0, 0.0, 0.0
    if h_rank and a_rank:
        rank_diff = a_rank - h_rank # Positiv om hemmalaget ligger bättre till
        stat_adj_1 += np.clip(rank_diff * 0.22, -3.5, 3.5)
        stat_adj_2 -= np.clip(rank_diff * 0.22, -3.5, 3.5)
        # Om två jämnstarka mittenlag möts ökar krysschansen (Poisson-effekt)
        if abs(rank_diff) <= 3:
            stat_adj_x += 1.2

    if h_form > 0 or a_form > 0:
        form_diff = h_form - a_form
        stat_adj_1 += np.clip(form_diff * 0.25, -2.5, 2.5)
        stat_adj_2 -= np.clip(form_diff * 0.25, -2.5, 2.5)

    # 5. Poisson/Fotbolls-korrigering för jämna matcher
    if product != "powerplay" and abs(odd_p1 - odd_p2) <= 10.0:
        stat_adj_x += 1.5  # Fotbollsmatcher som står 50/50 slutar oftare oavgjort än folket tror

    # 6. Vägsamman allt till en Total AI-Sannolikhet (Ensemble-modell)
    if tt_sum > 0:
        tt_p1, tt_px, tt_p2 = (tt1/tt_sum)*100, (ttx/tt_sum)*100, (tt2/tt_sum)*100
        raw_p1 = (odd_p1 * 0.86) + (tt_p1 * 0.14) + stat_adj_1
        raw_px = (odd_px * 0.88) + (tt_px * 0.12) + stat_adj_x
        raw_p2 = (odd_p2 * 0.86) + (tt_p2 * 0.14) + stat_adj_2
    else:
        raw_p1 = odd_p1 + stat_adj_1
        raw_px = odd_px + stat_adj_x
        raw_p2 = odd_p2 + stat_adj_2

    # Normalisera till 100 %
    tot_p = max(raw_p1 + raw_px + raw_p2, 1.0)
    ai_p1 = round((max(raw_p1, 1.0) / tot_p) * 100, 1)
    ai_px = round((max(raw_px, 1.0) / tot_p) * 100, 1)
    ai_p2 = round((max(raw_p2, 1.0) / tot_p) * 100, 1)

    # 7. Beräkna Edge (AI-sannolikhet minus Svenska Folket) & EV-kvot (AI / Folket)
    v1, vx, v2 = round(ai_p1 - s1, 1), round(ai_px - sx, 1), round(ai_p2 - s2, 1)
    ev1, evx, ev2 = ai_p1 / max(s1, 1.0), ai_px / max(sx, 1.0), ai_p2 / max(s2, 1.0)

    h2h = is_head_to_head(desc, sx, ai_px) if product == "powerplay" else False

    # 8. Beräkna "Spik-Index" (Hur lämplig är matchen som spik på kupongen?)
    # Vi letar efter kombinationen av hög vinstchans OCH att den inte är kupongens mest sönderstreckade fälla
    best_sign = max([("1", ai_p1, v1, s1), ("X", ai_px, vx, sx), ("2", ai_p2, v2, s2)], key=lambda x: x[1])
    spik_sign, spik_prob, spik_edge, spik_folket = best_sign
    
    if h2h:
        spik_index = 95.0 # På Powerplay älskar vi att spika X i spelardueller!
        spik_sign = "X"
    else:
        # En bra spik har hög sannolikhet (spik_prob) och vettigt streckvärde (spik_edge)
        spik_index = spik_prob + (spik_edge * 1.15)
        if strategy.startswith("Jobbtävlings-Jägaren") and spik_folket >= 72 and spik_edge < -7:
            spik_index -= 18.0 # Jägaren vägrar spika grovt överstreckade storfavoriter!

    match_data.append({
        "Nr": num, "Match": desc, "Stat": stat_str, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2,
        "p1": ai_p1, "px": ai_px, "p2": ai_p2,
        "v1": v1, "vx": vx, "v2": v2,
        "ev1": ev1, "evx": evx, "ev2": ev2,
        "tt1": tt1, "ttx": ttx, "tt2": tt2,
        "spik_sign": spik_sign, "spik_index": round(spik_index, 1)
    })

df = pd.DataFrame(match_data)

# --- 4. DYNAMISK RAM-ALLOKERING (BESTÄMMER ANTAL SPIKAR & GARDERINGAR AUTOMATISKT) ---
allowed_max_rows = max(int(max_budget / stake_per_row), 1)

# Hur stort grundsystem (ram) ska vi bygga innan vi handplockar de absolut bästa raderna?
# En ram på ca 8x - 25x budgeten ger perfekt balans: tillräckligt med spikar för styrka, och garderingar i skrällmatcherna!
if num_matches == 13:
    if allowed_max_rows <= 64:
        target_spikar, target_halv = 5, 4   # 5 spik, 4 halv, 4 hel = 1 296 rader i ramen
    elif allowed_max_rows <= 160:
        target_spikar, target_halv = 4, 4   # 4 spik, 4 halv, 5 hel = 3 888 rader i ramen
    elif allowed_max_rows <= 400:
        target_spikar, target_halv = 3, 4   # 3 spik, 4 halv, 6 hel = 11 664 rader i ramen
    else:
        target_spikar, target_halv = 3, 3   # 3 spik, 3 halv, 7 hel = 17 496 rader i ramen
else: # 8 matcher (Powerplay / Topptipset)
    if allowed_max_rows <= 50:
        target_spikar, target_halv = 3, 2   # 3 spik, 2 halv, 3 hel = 108 rader i ramen
    elif allowed_max_rows <= 150:
        target_spikar, target_halv = 2, 2   # 2 spik, 2 halv, 4 hel = 324 rader i ramen
    else:
        target_spikar, target_halv = 1, 2   # 1 spik, 2 halv, 5 hel = 972 rader i ramen

if strategy.startswith("Trygg"):
    target_spikar += 1

# Sortera alla matcher efter Spik-Index så att de bästa matcherna blir spikar, näst bästa halvgarderingar, och svåraste/bästa skrällmatcherna helgarderas!
ranked_indices = sorted(range(num_matches), key=lambda i: match_data[i]["spik_index"], reverse=True)
spik_matches = set(ranked_indices[:target_spikar])
halv_matches = set(ranked_indices[target_spikar:target_spikar + target_halv])

selections = []
match_roles = []
match_explanations = []

for i in range(num_matches):
    m = match_data[i]
    signs_ranked = sorted(
        ["1", "X", "2"],
        key=lambda s: (m[f"p{s.lower()}"] + m[f"v{s.lower()}"] * (1.5 if strategy.startswith("Jobb") else 0.9)),
        reverse=True
    )
    
    if i in spik_matches:
        chosen = [m["spik_sign"]]
        role = "🔒 AI-Spik"
        if m["H2H"]:
            exp = f"🎯 Spelarduell: Låser X ({int(m['px'])}% chans) för att spara krut till lagmatcherna"
        elif m[f"v{m['spik_sign'].lower()}"] >= 0:
            exp = f"💎 Omgångens Värdespik! {int(m['p'+m['spik_sign'].lower()])}% AI-chans & +{m['v'+m['spik_sign'].lower()]}% Edge"
        else:
            exp = f"⚡ Kupongens starkaste ryggrad ({int(m['p'+m['spik_sign'].lower()])}% AI-vinstchans)"
            
    elif i in halv_matches:
        chosen = sorted(signs_ranked[:2], key=lambda x: {"1":0, "X":1, "2":2}[x])
        role = "🛡️ Halvgardering"
        exp = f"⚖️ Låser de två starkaste värdetecknen ({', '.join(chosen)}), kastar sämsta tecknet"
        
    else:
        chosen = ["1", "X", "2"]
        role = "💣 Helgardering (Skrälljakt)"
        # Hitta vilket skrälltecken som har bäst övervärde i matchen
        best_dog = max(["1", "X", "2"], key=lambda s: m[f"v{s.lower()}"])
        dog_edge = m[f"v{best_dog.lower()}"]
        exp = f"🔥 Helgarderas! Jagar supervärdet på '{best_dog}' ({dog_edge:+}% AI-Edge mot folket)"

    selections.append(chosen)
    match_roles.append(role)
    match_explanations.append(exp)

# --- 5. NUMPY-VEKTORISERAD RADMOTOR (POÄNGSÄTTER ALLA RADER PÅ 0.1 SEKUNDER) ---
all_rows = list(itertools.product(*selections))
total_ram_rows = len(all_rows)

# Bygg NumPy-matriser för blixtsnabb beräkning av alla rader i ramen samtidigt
sign_to_idx = {"1": 0, "X": 1, "2": 2}
rows_idx = np.array([[sign_to_idx[s] for s in r] for r in all_rows], dtype=np.int32)

prob_matrix = np.array([[m["p1"], m["px"], m["p2"]] for m in match_data]) / 100.0
folket_matrix = np.maximum(np.array([[m["s1"], m["sx"], m["s2"]] for m in match_data]), 1.0) / 100.0
edge_matrix = np.array([[m["v1"], m["vx"], m["v2"]] for m in match_data])

match_idx = np.arange(num_matches)
row_probs = prob_matrix[match_idx, rows_idx]       # Sannolikhet per tecken
row_folket = folket_matrix[match_idx, rows_idx]     # Folkets streck per tecken
row_edges = edge_matrix[match_idx, rows_idx]        # AI-Edge per tecken

# 1. Sannolikhet att hela raden sitter (log-summa för numerisk precision)
rad_win_prob = np.prod(row_probs, axis=1)
rad_folket_prob = np.prod(row_folket, axis=1)

# 2. Uppskattad utdelning vid alla rätt
pool_share = 0.28 if num_matches == 13 else 0.70
est_payouts = np.round((pool_share / rad_folket_prob) * stake_per_row).astype(np.int64)

# 3. Matematiskt Väntevärde (Expected Value = Sannolikhet * Utdelning)
rad_ev = rad_win_prob * est_payouts
edge_sum = np.sum(row_edges, axis=1)
prob_sum = np.sum(row_probs * 100, axis=1)

# 4. Antal skrällar (tecken streckade under 23%) och kryss per rad
underdogs_count = np.sum(row_folket <= 0.23, axis=1)
draws_count = np.sum(rows_idx == 1, axis=1)

# 5. Beräkna Total AI-Score per rad beroende på vald profil
balance_penalty = np.zeros(total_ram_rows)
if num_matches == 13:
    # Straffa orealistiska rader (t.ex. 0 kryss, >6 kryss, eller 7+ megaskrällar samtidigt)
    balance_penalty += np.where((draws_count == 0) | (draws_count >= 7), -80.0, 0.0)
    balance_penalty += np.where(underdogs_count >= 6, -150.0, 0.0)
    balance_penalty += np.where((underdogs_count >= 2) & (underdogs_count <= 4), 45.0, 0.0)
else:
    balance_penalty += np.where(underdogs_count >= 4, -100.0, 0.0)
    balance_penalty += np.where((underdogs_count >= 1) & (underdogs_count <= 2), 35.0, 0.0)

if strategy.startswith("Helautomatisk Optimal"):
    total_scores = (prob_sum * 0.70) + (edge_sum * 1.75) + (np.clip(rad_ev, 0, 5) * 15.0) + balance_penalty
elif strategy.startswith("Jobbtävlings-Jägaren"):
    total_scores = (prob_sum * 0.45) + (edge_sum * 2.40) + (np.clip(rad_ev, 0, 8) * 20.0) + balance_penalty
else: # Trygg & Formstark
    total_scores = (prob_sum * 1.30) + (edge_sum * 0.60) + balance_penalty

# Automatisk utdelningsspärr: kräv att utdelningen minst täcker 3x hela din kupongbudget!
auto_min_payout = max(int(max_budget * 3), 250 if num_matches == 8 else 1500)
valid_mask = est_payouts >= auto_min_payout
if np.sum(valid_mask) < allowed_max_rows:
    valid_mask = np.ones(total_ram_rows, dtype=bool)

valid_indices = np.where(valid_mask)[0]
sorted_valid_indices = valid_indices[np.argsort(total_scores[valid_indices])[::-1]]

# --- 6. AUTOMATISKT ANTI-KLUMP-FILTER (GARANTERAR BRED TÄCKNING) ---
min_dist = 2 if (num_matches == 13 and allowed_max_rows <= 400) else 1
selected_idx = []

for idx in sorted_valid_indices:
    if len(selected_idx) >= allowed_max_rows:
        break
    cand = rows_idx[idx]
    if len(selected_idx) == 0:
        selected_idx.append(idx)
    else:
        # Vektoriserad kontroll av Hamming-avstånd mot alla redan valda rader
        existing = rows_idx[selected_idx]
        diffs = np.sum(existing != cand, axis=1)
        if np.all(diffs >= min_dist):
            selected_idx.append(idx)

# Fyll upp till exakt budget om Hamming-filtret var för strikt på slutet
if len(selected_idx) < allowed_max_rows:
    chosen_set = set(selected_idx)
    for idx in sorted_valid_indices:
        if len(selected_idx) >= allowed_max_rows:
            break
        if idx not in chosen_set:
            selected_idx.append(idx)
            chosen_set.add(idx)

filtered_rows = [all_rows[i] for i in selected_idx]
final_payouts = est_payouts[selected_idx]

# --- 7. PRESENTATION & DIREKT NEDLADDNING ---
st.subheader(f"🎯 Färdigoptimerad Kupong: {Export_Name} (Omgång {draw_number})")

if len(filtered_rows) > 0:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valda rader", f"{len(filtered_rows)} st", f"Från ram på {total_ram_rows:,} rader".replace(",", " "))
    c2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"Spikar: {target_spikar} st | Halv: {target_halv} st")
    c3.metric("Snittutdelning (Alla rätt)", f"~{int(np.mean(final_payouts)):,} kr".replace(",", " "), f"Min: {int(np.min(final_payouts)):,} kr".replace(",", " "))
    c4.metric("Maximal vinstpotential", f"{int(np.max(final_payouts)):,} kr".replace(",", " "), "Inkl. skrällrensare")

    if product in ["stryktipset", "europatipset"]:
        header_line = f"{Export_Name},Omg={draw_number}"
    else:
        header_line = f"{Export_Name},Omg={draw_number},Insats={stake_per_row}"
        
    lines = [header_line] + [f"E," + ",".join(r) for r in filtered_rows]
    file_content = "\n".join(lines)
    
    st.download_button(
        label=f"📥 Ladda ner färdig systemfil ({len(filtered_rows) * stake_per_row} kr) – Klar för inlämning!",
        data=file_content,
        file_name=f"{product}_omg_{draw_number}.txt",
        mime="text/plain",
        type="primary",
        use_container_width=True
    )

st.divider()

st.subheader("📊 AI-Motorns Helautomatiska Matchanalys & Ram")
table_rows = []
for i, row in df.iterrows():
    edges = {"1": row["v1"], "X": row["vx"], "2": row["v2"]}
    best_s = max(edges, key=edges.get)
    best_e = edges[best_s]
    
    tt_str = f"{row['tt1']}-{row['ttx']}-{row['tt2']}" if (row['tt1']+row['ttx']+row['tt2']) > 0 else "Ej släppt"
    
    table_rows.append({
        "Match": f"{row['Nr']}. {row['Match']}",
        "Tabell & Form": row["Stat"] if row["Stat"] else "Odds + Streck",
        "Folket (1-X-2)": f"{int(row['s1'])}% - {int(row['sx'])}% - {int(row['s2'])}%",
        "Experter (TT)": tt_str,
        "Total AI-Chans": f"{int(row['p1'])}% - {int(row['px'])}% - {int(row['p2'])}%",
        "Bästa Värde (Edge)": f"{best_s} ({best_e:+}%)",
        "AI-Beslut": match_roles[i],
        "Valda tecken": ", ".join(selections[i]),
        "Analys": match_explanations[i]
    })

st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
