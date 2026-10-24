import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
import re

st.set_page_config(page_title="AI Pool-Autopilot Ultra", layout="wide")
st.title("🤖 Helautomatisk AI-Autopilot – Stryktipset & Powerplay")

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
max_budget = st.sidebar.number_input("Total budget (kr)", min_value=10, max_value=5000, value=200, step=10)

if product in ["stryktipset", "europatipset"]:
    stake_per_row = 1
    st.sidebar.caption("ℹ️ Radinsats på Stryktipset är alltid 1 kr.")
else:
    stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

strategy = st.sidebar.selectbox(
    "3. Autopilot-profil",
    [
        "Helautomatisk Optimal (Maximerar EV)",
        "Jobbtävlings-Jägaren (Högre skrällfokus)",
        "Trygg & Formstark (Flest rätt)"
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
    except Exception:
        pass
    return h_rank, a_rank, h_form, a_form, f"Tabell: #{h_rank} vs #{a_rank}" if h_rank and a_rank else ""

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

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    ex = extra_map.get(num, {})
    
    sf = ev.get("svenskaFolket") or ex.get("svenskaFolket") or {}
    s1, sx, s2 = float(sf.get("one", 40) or 40), float(sf.get("x", 26) or 26), float(sf.get("two", 34) or 34)
    
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

    h_r, a_r, h_f, a_f, stat_str = extract_deep_stats(ev, ex)
    adj1 = np.clip((a_r - h_r) * 0.22, -3.5, 3.5) if h_r and a_r else 0.0
    adj2 = -adj1
    adgx = 1.2 if h_r and a_r and abs(a_r - h_r) <= 3 else 0.0

    if tt_sum > 0:
        raw_p1 = (p1 * 0.86) + ((tt1/tt_sum)*14) + adj1
        raw_px = (px * 0.88) + ((ttx/tt_sum)*12) + adgx
        raw_p2 = (p2 * 0.86) + ((tt2/tt_sum)*14) + adj2
    else:
        raw_p1, raw_px, raw_p2 = p1 + adj1, px + adgx, p2 + adj2

    tot = max(raw_p1 + raw_px + raw_p2, 1.0)
    ai_p1, ai_px, ai_p2 = round((raw_p1/tot)*100, 1), round((raw_px/tot)*100, 1), round((raw_p2/tot)*100, 1)
    
    v1, vx, v2 = round(ai_p1 - s1, 1), round(ai_px - sx, 1), round(ai_p2 - s2, 1)
    h2h = bool(re.search(r"\b[A-ZÅÄÖ]\.", desc)) if product == "powerplay" else False
    
    spik_sign, spik_prob, spik_edge = max([("1", ai_p1, v1), ("X", ai_px, vx), ("2", ai_p2, v2)], key=lambda x: x[1])
    spik_idx = 95.0 if h2h else spik_prob + (spik_edge * 1.15)

    match_data.append({
        "Nr": num, "Match": desc, "Stat": stat_str, "H2H": h2h,
        "s1": s1, "sx": sx, "s2": s2, "p1": ai_p1, "px": ai_px, "p2": ai_p2,
        "v1": v1, "vx": vx, "v2": v2, "tt1": tt1, "ttx": ttx, "tt2": tt2,
        "spik_sign": "X" if h2h else spik_sign, "spik_index": spik_idx
    })

df = pd.DataFrame(match_data)
allowed_max_rows = max(int(max_budget / stake_per_row), 1)

if num_matches == 13:
    t_spik, t_halv = (5, 4) if allowed_max_rows <= 64 else ((4, 4) if allowed_max_rows <= 160 else (3, 4))
else:
    t_spik, t_halv = (3, 2) if allowed_max_rows <= 50 else (2, 2)

ranked = sorted(range(num_matches), key=lambda i: match_data[i]["spik_index"], reverse=True)
spik_m, halv_m = set(ranked[:t_spik]), set(ranked[t_spik:t_spik + t_halv])

selections, roles, expl = [], [], []
for i in range(num_matches):
    m = match_data[i]
    if i in spik_m:
        selections.append([m["spik_sign"]])
        roles.append("🔒 AI-Spik")
        expl.append(f"Spikar {m['spik_sign']} ({int(m['p'+m['spik_sign'].lower()])}% AI-chans)")
    elif i in halv_m:
        sr = sorted(["1", "X", "2"], key=lambda s: m[f"p{s.lower()}"] + m[f"v{s.lower()}"], reverse=True)
        chosen = sorted(sr[:2], key=lambda x: {"1":0, "X":1, "2":2}[x])
        selections.append(chosen)
        roles.append("🛡️ Halv")
        expl.append(f"Låser {', '.join(chosen)}")
    else:
        selections.append(["1", "X", "2"])
        roles.append("💣 Hel")
        expl.append("Helgardering")

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

scores = (np.sum(p_mat[m_idx, r_idx]*100, axis=1) * 0.7) + (np.sum(e_mat[m_idx, r_idx], axis=1) * 1.7)
valid = np.where(payouts >= max(max_budget * 3, 1500 if num_matches == 13 else 250))[0]
if len(valid) < allowed_max_rows: valid = np.arange(len(all_rows))

sorted_v = valid[np.argsort(scores[valid])[::-1]]
selected_idx = []
for idx in sorted_v:
    if len(selected_idx) >= allowed_max_rows: break
    cand = r_idx[idx]
    if not selected_idx or all(np.sum(r_idx[selected_idx] != cand, axis=1) >= 1):
        selected_idx.append(idx)

if len(selected_idx) < allowed_max_rows:
    for idx in sorted_v:
        if len(selected_idx) >= allowed_max_rows: break
        if idx not in selected_idx: selected_idx.append(idx)

filtered_rows = [all_rows[i] for i in selected_idx]
final_payouts = payouts[selected_idx]

st.subheader(f"🎯 Färdigoptimerad Kupong: {Export_Name} (Omgång {draw_number})")
if filtered_rows:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rader", f"{len(filtered_rows)} st")
    c2.metric("Kostnad", f"{len(filtered_rows) * stake_per_row} kr")
    c3.metric("Snittutdelning", f"~{int(np.mean(final_payouts)):,} kr".replace(",", " "))
    c4.metric("Maxvinst", f"{int(np.max(final_payouts)):,} kr".replace(",", " "))

    header = f"{Export_Name},Omg={draw_number}" if product in ["stryktipset", "europatipset"] else f"{Export_Name},Omg={draw_number},Insats={stake_per_row}"
    file_content = "\n".join([header] + ["E," + ",".join(r) for r in filtered_rows])
    
    st.download_button("📥 Ladda ner systemfil – Klar för inlämning!", data=file_content, file_name=f"{product}_{draw_number}.txt", mime="text/plain", type="primary", use_container_width=True)

st.divider()
st.subheader("📊 AI-Analys")
table_rows = [{"Match": f"{m['Nr']}. {m['Match']}", "AI-Chans": f"{int(m['p1'])}% - {int(m['px'])}% - {int(m['p2'])}%", "AI-Beslut": roles[i], "Valda tecken": ", ".join(selections[i]), "Analys": expl[i]} for i, m in enumerate(match_data)]
st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
