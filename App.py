import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
import re

st.set_page_config(page_title="AI Pool-Autopilot Ultra", layout="wide")
st.title("🤖 Helautomatisk AI-Autopilot – Stryktipset & Powerplay")

product_map = {
    "Powerplay (8 matcher)": "powerplay",
    "Stryktipset (13 matcher)": "stryktipset",
    "Europatipset (13 matcher)": "europatipset",
    "Topptipset (8 matcher)": "topptipset"
}
selected_label = st.sidebar.selectbox("1. Välj spelform", list(product_map.keys()))
product = product_map[selected_label]
Export_Name = selected_label.split(" ")[0]

st.sidebar.divider()
st.sidebar.subheader("💰 2. Din Budget")
max_budget = st.sidebar.number_input("Total budget (kr)", min_value=10, max_value=5000, value=150, step=10)

if product in ["stryktipset", "europatipset"]:
    stake_per_row = 1
    st.sidebar.caption("ℹ️ Radinsats på Stryktipset är alltid 1 kr.")
else:
    stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

strategy = st.sidebar.selectbox(
    "3. Autopilot-profil",
    [
        "Trygg & Säker (Maximerar chans till 8/13 rätt + X-skydd)",
        "Helautomatisk Optimal (Balanserar chans & utdelning)",
        "Jobbtävlings-Jägaren (Fäller överstreckade favoriter & jagar miljonen)"
    ]
)

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
                    sr = requests.get(f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws/{d_num}/statistics", headers=headers, timeout=5)
                    if sr.status_code == 200:
                        d["_extra_stats"] = sr.json().get("statistics", {})
                except Exception:
                    pass
        return draws_list
    except Exception as e:
        st.error(f"Kunde inte hämta data: {e}")
        return []

def parse_odd(val):
    return float(str(val).replace(",", ".")) if val else 0.0

def calc_form_pts(form_raw):
    if not form_raw: return 0
    s = "".join([str(x.get("outcome", x)) for x in form_raw]) if isinstance(form_raw, list) else str(form_raw)
    return sum(3 if ch.upper() in ["W","V","3","1"] else (1 if ch.upper() in ["D","O","X"] else 0) for ch in s[-5:])

def extract_deep_stats(ev, extra_ev_stat):
    h_rank, a_rank, h_form, a_form = None, None, 0.0, 0.0
    stat_parts = []
    try:
        for p in ev.get("match", {}).get("participants", []):
            t = p.get("type", "").lower()
            r = p.get("ranking") or p.get("tablePosition")
            f = calc_form_pts(p.get("form") or p.get("trend"))
            if "home" in t: h_rank, h_form = (int(r), f) if r else (None, f)
            elif "away" in t: a_rank, a_form = (int(r), f) if r else (None, f)
        if extra_ev_stat:
            for row in (extra_ev_stat.get("standings") or extra_ev_stat.get("table") or []):
                if row.get("isHomeTeam") or row.get("teamType") == "home": h_rank = h_rank or row.get("position")
                elif row.get("isAwayTeam") or row.get("teamType") == "away": a_rank = a_rank or row.get("position")
            hf = extra_ev_stat.get("homeForm") or extra_ev_stat.get("formHome")
            af = extra_ev_stat.get("awayForm") or extra_ev_stat.get("formAway")
            if hf and not h_form: h_form = calc_form_pts(hf)
            if af and not a_form: a_form = calc_form_pts(af)
        if h_rank and a_rank: stat_parts.append(f"Tabell: #{h_rank} vs #{a_rank}")
        if h_form > 0 or a_form > 0: stat_parts.append(f"Form: {int(h_form)}p-{int(a_form)}p")
    except Exception:
        pass
    return h_rank, a_rank, h_form, a_form, " | ".join(stat_parts)

draws = fetch_draws(product)
if not draws:
    st.warning("Ingen öppen omgång hittades.")
    st.stop()

draw_options = {f"Omgång {d.get('drawNumber')} - {d.get('drawComment', '')}": d for d in draws}
draw = draws[list(draw_options.keys()).index(st.sidebar.selectbox("Välj omgång", list(draw_options.keys())))]
draw_number = draw.get("drawNumber")

if st.sidebar.button("🔄 Uppdatera live-statistik"):
    st.cache_data.clear()
    st.rerun()

extra_map = {ev.get("eventNumber"): ev for ev in draw.get("_extra_stats", {}).get("events", draw.get("_extra_stats", {}).get("drawEvents", []))}
events = draw.get("drawEvents", [])
num_matches = len(events)
match_data = []

is_safe_mode = strategy.startswith("Trygg")
is_hunter_mode = strategy.startswith("Jobb")

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    ex = extra_map.get(num, {})
    
    sf = ev.get("svenskaFolket") or ex.get("svenskaFolket") or {}
    s1, sx, s2 = float(sf.get("one", 40) or 40), float(sf.get("x", 24) or 24), float(sf.get("two", 36) or 36)
    
    tt = ev.get("tioTidningarsTips") or ev.get("newspaperAdvice") or ex.get("tioTidningarsTips") or {}
    tt1, ttx, tt2 = int(tt.get("one", 0) or 0), int(tt.get("x", 0) or 0), int(tt.get("two", 0) or 0)
    tt_sum = tt1 + ttx + tt2
    
    odds = ev.get("odds") or ex.get("odds") or {}
    o1, ox, o2 = parse_odd(odds.get("one")), parse_odd(odds.get("x")), parse_odd(odds.get("two"))
    
    if o1 > 0 and ox > 0 and o2 > 0:
        inv1, invx, inv2 = (1.0/o1)**1.05, (1.0/ox)**1.05, (1.0/o2)**1.05
        tot_inv = inv1 + invx + inv2
        p1, px, p2 = (inv1/tot_inv)*100, (invx/tot_inv)*100, (inv2/tot_inv)*100
    else:
        p1, px, p2 = s1, sx, s2

    h2h = bool(re.search(r"\b[A-ZÅÄÖ]\.", desc) or sx >= 36 or px >= 36) if product == "powerplay" else False
    h_r, a_r, h_f, a_f, stat_str = extract_deep_stats(ev, ex)
    
    # FIX 1: Nu vägs både Tabell OCH Formkurva in i justeringen!
    rank_adj = np.clip((a_r - h_r) * 0.22, -3.5, 3.5) if (h_r and a_r and not h2h) else 0.0
    form_adj = np.clip((h_f - a_f) * 0.25, -2.5, 2.5) if ((h_f > 0 or a_f > 0) and not h2h) else 0.0
    adj1 = float(rank_adj + form_adj)
    adj2 = -adj1
    
    # FIX 4a: Kryss-boost i jämna matcher (både hockey-övertid och jämna fotbollsmatcher)
    adgx = 0.0
    if not h2h and abs(p1 - p2) <= 11.0:
        adgx = 2.0 if product == "powerplay" else 1.5

    if tt_sum > 0:
        raw_p1 = (p1 * 0.86) + ((tt1/tt_sum)*14) + adj1
        raw_px = (px * 0.88) + ((ttx/tt_sum)*12) + adgx
        raw_p2 = (p2 * 0.86) + ((tt2/tt_sum)*14) + adj2
    else:
        raw_p1, raw_px, raw_p2 = p1 + adj1, px + adgx, p2 + adj2

    tot = max(raw_p1 + raw_px + raw_p2, 1.0)
    ai_p1, ai_px, ai_p2 = round((raw_p1/tot)*100, 1), round((raw_px/tot)*100, 1), round((raw_p2/tot)*100, 1)
    v1, vx, v2 = round(ai_p1 - s1, 1), round(ai_px - sx, 1), round(ai_p2 - s2, 1)
    
    cands = [("1", ai_p1, v1, s1), ("X", ai_px, vx, sx), ("2", ai_p2, v2, s2)]
    
    if h2h:
        spik_sign = "X"
        spik_idx = 65.0 + ai_px
    elif is_hunter_mode:
        viable = [c for c in cands if c[1] >= 35.0] or cands
        spik_sign, spik_prob, spik_edge, spik_folk = max(viable, key=lambda x: x[1] + (x[2] * 1.8))
        spik_idx = spik_prob + (spik_edge * 1.8)
        if spik_folk >= 60.0 and spik_edge <= -5.0:
            spik_idx -= 25.0
    else:
        spik_sign, spik_prob, spik_edge, spik_folk = max(cands, key=lambda x: x[1])
        edge_weight = 0.35 if is_safe_mode else 1.15
        spik_idx = spik_prob + (spik_edge * edge_weight)

    match_data.append({
        "Nr": num, "Match": desc, "Stat": stat_str, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2, "p1": ai_p1, "px": ai_px, "p2": ai_p2,
        "v1": v1, "vx": vx, "v2": v2, "tt1": tt1, "ttx": ttx, "tt2": tt2,
        "spik_sign": spik_sign, "spik_index": spik_idx
    })

df = pd.DataFrame(match_data)
allowed_max_rows = max(int(max_budget / stake_per_row), 1)

if num_matches == 13:
    t_spik, t_halv = (5, 4) if allowed_max_rows <= 64 else ((4, 4) if allowed_max_rows <= 160 else (3, 4))
else:
    if allowed_max_rows <= 48: t_spik, t_halv = 3, 2
    elif allowed_max_rows <= 160: t_spik, t_halv = 2, 3
    else: t_spik, t_halv = 1, 3

# FIX 2: Trygg & Säker får en extra spik så att ramen blir tätare och säkrare!
if is_safe_mode and t_spik < (6 if num_matches == 13 else 4):
    t_spik += 1

ranked = sorted(range(num_matches), key=lambda i: match_data[i]["spik_index"], reverse=True)
spik_m, halv_m = set(ranked[:t_spik]), set(ranked[t_spik:t_spik + t_halv])

selections, roles, expl = [], [], []
for i in range(num_matches):
    m = match_data[i]
    if i in spik_m:
        s_sign = m["spik_sign"]
        selections.append([s_sign])
        s_prob = int(m['p'+s_sign.lower()])
        s_edge = m['v'+s_sign.lower()]
        if m["H2H"]:
            roles.append("🔒 H2H-Spik")
            expl.append(f"🎯 H2H-Spik X ({int(m['px'])}%)")
        elif is_hunter_mode and s_edge > 0:
            roles.append("💎 Värdespik")
            expl.append(f"💎 Jägarens Värdespik: {s_sign} ({s_prob}% chans, {s_edge:+}% Edge!)")
        else:
            roles.append("🔒 Säker Spik" if is_safe_mode else "🔒 AI-Spik")
            expl.append(f"⚡ Stark spik: {s_sign} ({s_prob}% AI-chans)")
    elif i in halv_m:
        if m["H2H"]:
            best_w = "1" if m["p1"] >= m["p2"] else "2"
            chosen = sorted(["X", best_w], key=lambda x: {"1":0, "X":1, "2":2}[x])
            expl.append(f"🎯 H2H-Lås: {''.join(chosen)} (Täcker {int(m['px']+m['p'+best_w.lower()])}% av duellen!)")
        elif product == "powerplay" and (is_safe_mode or (not is_hunter_mode and abs(m["p1"] - m["p2"]) <= 12)):
            best_team = "1" if m["p1"] >= m["p2"] else "2"
            chosen = ["1", "X"] if best_team == "1" else ["X", "2"]
            expl.append(f"🛡️ Hockey-lås ({''.join(chosen)}): Säkrat med kryss vid full tid!")
        else:
            # FIX 3: I Jägaren straffas grovt överstreckade favoriter även i halvgarderingar (möjliggör X2/1X-skrällås!)
            def sign_score(s):
                prob, edge, folk = m[f"p{s.lower()}"], m[f"v{s.lower()}"], m[f"s{s.lower()}"]
                if is_safe_mode: return prob + (edge * 0.3)
                if is_hunter_mode:
                    pen = -18.0 if (folk >= 65.0 and edge <= -7.0) else 0.0
                    return prob + (edge * 2.0) + pen
                return prob + (edge * 0.9)
            sr = sorted(["1", "X", "2"], key=sign_score, reverse=True)
            chosen = sorted(sr[:2], key=lambda x: {"1":0, "X":1, "2":2}[x])
            expl.append(f"⚖️ Halvgardering: {', '.join(chosen)} ({int(sum(m['p'+c.lower()] for c in chosen))}% chans)")
        selections.append(chosen)
        roles.append("🛡️ Halvgardering")
    else:
        selections.append(["1", "X", "2"])
        roles.append("💣 Helgardering")
        best_dog = max(["1", "X", "2"], key=lambda s: m[f"v{s.lower()}"])
        expl.append(f"🔥 Helgarderad (Jagar skrällvärdet på '{best_dog}': {m['v'+best_dog.lower()]:+}% Edge)")

all_rows = list(itertools.product(*selections))
sign_map = {"1": 0, "X": 1, "2": 2}
r_idx = np.array([[sign_map[s] for s in r] for r in all_rows], dtype=np.int32)

p_mat = np.array([[m["p1"], m["px"], m["p2"]] for m in match_data]) / 100.0
f_mat = np.maximum(np.array([[m["s1"], m["sx"], m["s2"]] for m in match_data]), 1.0) / 100.0
e_mat = np.array([[m["v1"], m["vx"], m["v2"]] for m in match_data])

m_idx = np.arange(num_matches)
r_prob = np.prod(p_mat[m_idx, r_idx], axis=1)
r_folk = np.prod(f_mat[m_idx, r_idx], axis=1)
payouts = np.round(((0.28 if num_matches == 13 else 0.70) / r_folk) * stake_per_row).astype(np.int64)

prob_sum = np.sum(p_mat[m_idx, r_idx]*100, axis=1)
edge_sum = np.sum(e_mat[m_idx, r_idx], axis=1)
underdogs = np.sum(f_mat[m_idx, r_idx] <= 0.22, axis=1)
draws_cnt = np.sum(r_idx == 1, axis=1)

# FIX 4b: Återställt kryss-filter för 13-matcherskuponger (undviker 0 kryss eller 7+ kryss)
draw_pen = np.where((draws_cnt == 0) | (draws_cnt >= 7), -80.0, 0.0) if num_matches == 13 else 0.0

if is_safe_mode:
    dog_pen = np.where(underdogs >= (3 if num_matches == 8 else 5), -120.0, 0.0)
    scores = (prob_sum * 1.45) + (edge_sum * 0.45) + dog_pen + draw_pen
    min_req_payout = int(max_budget * 0.8)
elif is_hunter_mode:
    dog_bonus = np.where((underdogs >= 2) & (underdogs <= (4 if num_matches == 8 else 6)), 55.0, -90.0)
    scores = (prob_sum * 0.45) + (edge_sum * 2.40) + dog_bonus + draw_pen
    min_req_payout = max(int(max_budget * 3.5), 400 if num_matches == 8 else 3000)
else:
    dog_pen = np.where(underdogs >= (4 if num_matches == 8 else 6), -100.0, 0.0)
    scores = (prob_sum * 0.85) + (edge_sum * 1.50) + dog_pen + draw_pen
    min_req_payout = max(int(max_budget * 1.8), 180 if num_matches == 8 else 1200)

valid = np.where(payouts >= min_req_payout)[0]
if len(valid) < allowed_max_rows: valid = np.arange(len(all_rows))

sorted_v = valid[np.argsort(scores[valid])[::-1]]

min_dist = 2 if (num_matches == 13 and allowed_max_rows <= 400) else 1
selected_idx = []
for idx in sorted_v:
    if len(selected_idx) >= allowed_max_rows: break
    cand = r_idx[idx]
    if not selected_idx or np.all(np.sum(r_idx[selected_idx] != cand, axis=1) >= min_dist):
        selected_idx.append(idx)

if len(selected_idx) < allowed_max_rows:
    chosen_set = set(selected_idx)
    for idx in sorted_v:
        if len(selected_idx) >= allowed_max_rows: break
        if idx not in chosen_set:
            selected_idx.append(idx)
            chosen_set.add(idx)

filtered_rows = [all_rows[i] for i in selected_idx]
final_payouts = payouts[selected_idx]

st.subheader(f"🎯 Färdigoptimerad Kupong: {Export_Name} (Omgång {draw_number})")
if filtered_rows:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valda rader", f"{len(filtered_rows)} st", f"Av {len(all_rows)} i ramen")
    c2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"Spik: {t_spik} | Halv: {t_halv}")
    c3.metric("Snittutdelning", f"~{int(np.mean(final_payouts)):,} kr".replace(",", " "))
    c4.metric("Maxvinst", f"{int(np.max(final_payouts)):,} kr".replace(",", " "))

    header = f"{Export_Name},Omg={draw_number}" if product in ["stryktipset", "europatipset"] else f"{Export_Name},Omg={draw_number},Insats={stake_per_row}"
    file_content = "\n".join([header] + ["E," + ",".join(r) for r in filtered_rows])
    
    st.download_button("📥 Ladda ner systemfil – Klar för inlämning!", data=file_content, file_name=f"{product}_{draw_number}.txt", mime="text/plain", type="primary", use_container_width=True)

st.divider()
st.subheader("📊 AI-Motorns Matchanalys")
table_rows = [{
    "Match": f"{m['Nr']}. {m['Match']}",
    "Statistik": m["Stat"] if m["Stat"] else "Odds + TT",
    "Typ": "🎯 H2H" if m["H2H"] else "⚽/🏒 Match",
    "Folket (1-X-2)": f"{int(m['s1'])}%-{int(m['sx'])}%-{int(m['s2'])}%",
    "AI-Chans": f"{int(m['p1'])}%-{int(m['px'])}%-{int(m['p2'])}%",
    "Bästa Edge": f"{max(['1','X','2'], key=lambda s: m['v'+s.lower()])} ({max(m['v1'],m['vx'],m['v2']):+}%)",
    "Beslut": roles[i],
    "Tecken": ", ".join(selections[i]),
    "Kommentar": expl[i]
} for i, m in enumerate(match_data)]
st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
