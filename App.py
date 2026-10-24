import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
import re

st.set_page_config(page_title="AI Pool-Autopilot Ultra", layout="wide")
st.title("🤖 Helautomatisk AI-Autopilot – All Statistik Inbakad")
st.markdown("100 % automatisk analys av **Odds, Streckvärde, Tabell, Form, Experter (TT) & Målförväntan**.")

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

# --- 2. HÄMTA ALL DATA + STATISTIK FRÅN SVENSKA SPEL ---
@st.cache_data(ttl=120)
def fetch_draws(prod):
    url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        draws_list = r.json().get("draws", [])
        for d in draws_list:
            d_num = d.get("drawNumber")
            if d_num:
                try:
                    s_url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws/{d_num}/statistics"
                    sr = requests.get(s_url, headers=headers, timeout=6)
                    if sr.status_code == 200:
                        d["_extra_stats"] = sr.json().get("statistics", {})
                except Exception:
                    pass
        return draws_list
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

def calc_form_pts(form_raw):
    pts = 0
    if isinstance(form_raw, str) and form_raw:
        for ch in form_raw.upper()[-5:]:
            if ch in ["W", "V", "3"]:
                pts += 3
            elif ch in ["D", "O", "X", "1"]:
                pts += 1
    elif isinstance(form_raw, list):
        for item in form_raw[-5:]:
            res = str(item.get("outcome", item) if isinstance(item, dict) else item).upper()
            if res in ["W", "V", "1", "WIN"] or "WIN" in res:
                pts += 3
            elif res in ["D", "O", "X", "DRAW"] or "DRAW" in res:
                pts += 1
    return pts

def extract_deep_stats(ev, extra_ev_stat):
    h_rank, a_rank = None, None
    h_form_pts, a_form_pts = 0.0, 0.0
    stat_summary = []
    try:
        match_obj = ev.get("match", {})
        for p in match_obj.get("participants", []):
            t_type = p.get("type", "").lower()
            rank = p.get("ranking") or p.get("tablePosition")
            f_pts = calc_form_pts(p.get("form") or p.get("trend") or "")
            if "home" in t_type:
                if rank:
                    h_rank = int(rank)
                if f_pts:
                    h_form_pts = f_pts
            elif "away" in t_type:
                if rank:
                    a_rank = int(rank)
                if f_pts:
                    a_form_pts = f_pts

        if extra_ev_stat:
            standings = extra_ev_stat.get("standings") or extra_ev_stat.get("table") or []
            for row in standings:
                if row.get("isHomeTeam") or row.get("teamType") == "home":
                    h_rank = h_rank or row.get("position") or row.get("rank")
                elif row.get("isAwayTeam") or row.get("teamType") == "away":
                    a_rank = a_rank or row.get("position") or row.get("rank")
            h_f = extra_ev_stat.get("homeForm") or extra_ev_stat.get("formHome")
            a_f = extra_ev_stat.get("awayForm") or extra_ev_stat.get("formAway")
            if h_f and not h_form_pts:
                h_form_pts = calc_form_pts(h_f)
            if a_f and not a_form_pts:
                a_form_pts = calc_form_pts(a_f)

        if h_rank and a_rank:
            stat_summary.append(f"Tabell: #{h_rank} vs #{a_rank}")
        if h_form_pts > 0 or a_form_pts > 0:
            stat_summary.append(f"Form(5): {int(h_form_pts)}p vs {int(a_form_pts)}p")
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
draw_number = draw.get("drawNumber")

if st.sidebar.button("🔄 Uppdatera all live-statistik"):
    st.cache_data.clear()
    st.rerun()

extra_stats_map = {}
extra_stats_obj = draw.get("_extra_stats", {})
for stat_ev in extra_stats_obj.get("events", extra_stats_obj.get("drawEvents", [])):
    e_num = stat_ev.get("eventNumber")
    if e_num:
        extra_stats_map[e_num] = stat_ev

# --- 3. HELAUTOMATISK STATISTIKMOTOR ---
events = draw.get("drawEvents", [])
num_matches = len(events)
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    extra_ev = extra_stats_map.get(num, {})

    sf = ev.get("svenskaFolket") or extra_ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    if s1 + sx + s2 == 0:
        s1, sx, s2 = 40.0, 26.0, 34.0

    tt = (
        ev.get("tioTidningarsTips")
        or ev.get("newspaperAdvice")
        or extra_ev.get("tioTidningarsTips")
        or extra_ev.get("newspaperAdvice")
        or {}
    )
    tt1 = int(tt.get("one", 0) or 0)
    ttx = int(tt.get("x", 0) or 0)
    tt2 = int(tt.get("two", 0) or 0)
    tt_sum = tt1 + ttx + tt2

    odds = ev.get("odds") or extra_ev.get("odds") or {}
    o1 = parse_odd(odds.get("one"))
    ox = parse_odd(odds.get("x"))
    o2 = parse_odd(odds.get("two"))

    if o1 > 0 and ox > 0 and o2 > 0:
        inv1 = (1.0 / o1) ** 1.05
        invx = (1.0 / ox) ** 1.05
        inv2 = (1.0 / o2) ** 1.05
        total_inv = inv1 + invx + inv2
        odd_p1 = (inv1 / total_inv) * 100.0
        odd_px = (invx / total_inv) * 100.0
        odd_p2 = (inv2 / total_inv) * 100.0
    else:
        odd_p1, odd_px, odd_p2 = s1, sx, s2

    h_rank, a_rank, h_form, a_form, stat_str = extract_deep_stats(ev, extra_ev)
    stat_adj_1, stat_adj_x, stat_adj_2 = 0.0, 0.0, 0.0

    if h_rank and a_rank:
        rank_diff = a_rank - h_rank
        adj_r = float(np.clip(rank_diff * 0.22, -3.5, 3.5))
        stat_adj_1 += adj_r
        stat_adj_2 -= adj_r
        if abs(rank_diff) <= 3:
            stat_adj_x += 1.2

    if h_form > 0 or a_form > 0:
        form_diff = h_form - a_form
        adj_f = float(np.clip(form_diff * 0.25, -2.5, 2.5))
        stat_adj_1 += adj_f
        stat_adj_2 -= adj_f

    if product != "powerplay" and abs(odd_p1 - odd_p2) <= 10.0:
        stat_adj_x += 1.5

    if tt_sum > 0:
        tt_p1 = (tt1 / tt_sum) * 100.0
        tt_px = (ttx / tt_sum) * 100.0
        tt_p2 = (tt2 / tt_sum) * 100.0
        raw_p1 = (odd_p1 * 0.86) + (tt_p1 * 0.14) + stat_adj_1
        raw_px = (odd_px * 0.88) + (tt_px * 0.12) + stat_adj_x
        raw_p2 = (odd_p2 * 0.86) + (tt_p2 * 0.14) + stat_adj_2
    else:
        raw_p1 = odd_p1 + stat_adj_1
        raw_px = odd_px + stat_adj_x
        raw_p2 = odd_p2 + stat_adj_2

    tot_p = max(raw_p1 + raw_px + raw_p2, 1.0)
    ai_p1 = round((max(raw_p1, 1.0) / tot_p) * 100.0, 1)
    ai_px = round((max(raw_px, 1.0) / tot_p) * 100.0, 1)
    ai_p2 = round((max(raw_p2, 1.0) / tot_p) * 100.0, 1)

    v1 = round(ai_p1 - s1, 1)
    vx = round(ai_px - sx, 1)
    v2 = round(ai_p2 - s2, 1)

    h2h = is_head_to_head(desc, sx, ai_px) if product == "powerplay" else False

    candidates = [("1", ai_p1, v1, s1), ("X", ai_px, vx, sx), ("2", ai_p2, v2, s2)]
    spik_sign, spik_prob, spik_edge, spik_folket = max(candidates, key=lambda x: x[1])

    if h2h:
        spik_index = 95.0
        spik_sign = "X"
    else:
        spik_index = spik_prob + (spik_edge * 1.15)
        if strategy.startswith("Jobbtävlings-Jägaren") and spik_folket >= 72 and spik_edge < -7:
            spik_index -= 18.0

    match_data.append({
        "Nr": num, "Match": desc, "Stat": stat_str, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2,
        "p1": ai_p1, "px": ai_px, "p2": ai_p2,
        "v1": v1, "vx": vx, "v2": v2,
        "tt1": tt1, "ttx": ttx, "tt2": tt2,
        "spik_sign": spik_sign, "spik_index": round(spik_index, 1)
    })

df = pd.DataFrame(match_data)

# --- 4. DYNAMISK RAM-ALLOKERING ---
allowed_max_rows = max(int(max_budget / stake_per_row), 1)

if num_matches == 13:
    if allowed_max_rows <= 64:
        target_spikar, target_halv = 5, 4
    elif allowed_max_rows <= 160:
        target_spikar, target_halv = 4, 4
    elif allowed_max_rows <= 400:
        target_spikar, target_halv = 3, 4
    else:
        target_spikar, target_halv = 3, 3
else:
    if allowed_max_rows <= 50:
        target_spikar, target_halv = 3, 2
    elif allowed_max_rows <= 150:
        target_spikar, target_halv = 2, 2
    else:
        target_spikar, target_halv = 1, 2

if strategy.startswith("Trygg"):
    target_spikar += 1

ranked_indices = sorted(range(num_matches), key=lambda i: match_data[i]["spik_index"], reverse=True)
spik_matches = set(ranked_indices[:target_spikar])
halv_matches = set(ranked_indices[target_spikar:target_spikar + target_halv])

selections = []
match_roles = []
match_explanations = []

for i in range(num_matches):
    m = match_data[i]
    w_edge = 1.5 if strategy.startswith("Jobb") else 0.9
    signs_ranked = sorted(
        ["1", "X", "2"],
        key=lambda s: (m[f"p{s.lower()}"] + m[f"v{s.lower()}"] * w_edge),
        reverse=True
    )

    if i in spik_matches:
        sp_s = m["spik_sign"]
        chosen = [sp_s]
        role = "🔒 AI-Spik"
        sp_prob = int(m[f"p{sp_s.lower()}"])
        sp_edg = m[f"v{sp_s.lower()}"]
        if m["H2H"]:
            exp = f"🎯 Spelarduell: Låser X ({int(m['px'])}% chans) för att spara krut"
        elif sp_edg >= 0:
            exp = f"💎 Omgångens Värdespik! {sp_prob}% AI-chans & +{sp_edg}% Edge"
        else:
            exp = f"⚡ Kupongens starkaste ryggrad ({sp_prob}% AI-vinstchans)"
    elif i in halv_matches:
        order_map = {"1": 0, "X": 1, "2": 2}
        chosen = sorted(signs_ranked[:2], key=lambda x: order_map[x])
        role = "🛡️ Halvgardering"
        exp = f"⚖️ Låser de två starkaste värdetecknen ({', '.join(chosen)}), kastar sämsta"
    else:
        chosen = ["1", "X", "2"]
        role = "💣 Helgardering (Skrälljakt)"
        best_dog = max(["1", "X", "2"], key=lambda s: m[f"v{s.lower()}"])
        dog_edge = m[f"v{best_dog.lower()}"]
        exp = f"🔥 Helgarderas! Jagar supervärdet på '{best_dog}' ({dog_edge:+}% AI-Edge)"

    selections.append(chosen)
    match_roles.append(role)
    match_explanations.append(exp)

# --- 5. NUMPY-VEKTORISERAD RADMOTOR ---
all_rows = list(itertools.product(*selections))
total_ram_rows = len(all_rows)

sign_to_idx = {"1": 0, "X": 1, "2": 2}
rows_idx = np.array([[sign_to_idx[s] for s in r] for r in all_rows], dtype=np.int32)

prob_matrix = np.array([[m["p1"], m["px"], m["p2"]] for m in match_data]) / 100.0
folket_matrix = np.maximum(np.array([[m["s1"], m["sx"], m["s2"]] for m in match_data]), 1.0) / 100.0
edge_matrix = np.array([[m["v1"], m["vx"], m["v2"]] for m in match_data])

match_idx = np.arange(num_matches)
row_probs = prob_matrix[match_idx, rows_idx]
row_folket = folket_matrix[match_idx, rows_idx]
row_edges = edge_matrix[match_idx, rows_idx]

rad_win_prob = np.prod(row_probs, axis=1)
rad_folket_prob = np.prod(row_folket, axis=1)

pool_share = 0.28 if num_matches == 13 else 0.70
est_payouts = np.round((pool_share / rad_folket_prob) * stake_per_row).astype(np.int64)

rad_ev = rad_win_prob * est_payouts
edge_sum = np.sum(row_edges, axis=1)
prob_sum = np.sum(row_probs * 100.0, axis=1)

underdogs_count = np.sum(row_folket <= 0.23, axis=1)
draws_count = np.sum(rows_idx == 1, axis=1)

balance_penalty = np.zeros(total_ram_rows)
if num_matches == 13:
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
else:
    total_scores = (prob_sum * 1.30) + (edge_sum * 0.60) + balance_penalty

auto_min_payout = max(int(max_budget * 3), 250 if num_matches == 8 else 1500)
valid_mask = est_payouts >= auto_min_payout
if np.sum(valid_mask) < allowed_max_rows:
    valid_mask = np.ones(total_ram_rows, dtype=bool)

valid_indices = np.where(valid_mask)[0]
sorted_valid_indices = valid_indices[np.argsort(total_scores[valid_indices])[::-1]]

# --- 6. AUTOMATISKT ANTI-KLUMP-FILTER ---
min_dist = 2 if (num_matches == 13 and allowed_max_rows <= 400) else 1
selected_idx = []

for idx in sorted_valid_indices:
    if len(selected_idx) >= allowed_max_rows:
        break
    cand = rows_idx[idx]
    if len(selected_idx) == 0:
        selected_idx.append(idx)
    else:
        existing = rows_idx[selected_idx]
        diffs = np.sum(existing != cand, axis=1)
        if np.all(diffs >= min_dist):
            selected_idx.append(idx)

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
    c1.metric("Valda rader", f"{len(filtered_rows)} st", f"Ram: {total_ram_rows:,} rader".replace(",", " "))
    c2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"Spikar: {target_spikar} | Halv: {target_halv}")
    c3.metric("Snittutdelning", f"~{int(np.mean(final_payouts)):,} kr".replace(",", " "), f"Min: {int(np.min(final_payouts)):,} kr".replace(",", " "))
    c4.metric("Maxvinstpotential", f"{int(np.max(final_payouts)):,} kr".replace(",", " "), "Inkl. skrällrensare")

    if product in ["stryktipset", "europatipset"]:
        header_line = f"{Export_Name},Omg={draw_number}"
    else:
        header_line = f"{Export_Name},Omg={draw_number},Insats={stake_per_row}"

    lines = [header_line] + ["E," + ",".join(r) for r in filtered_rows]
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
    tt_tot = row["tt1"] + row["ttx"] + row["tt2"]
    tt_str = f"{row['tt1']}-{row['ttx']}-{row['tt2']}" if tt_tot > 0 else "Ingår i oddsen"

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
