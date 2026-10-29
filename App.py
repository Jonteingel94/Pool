import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
from scipy.special import softmax
from scipy.optimize import brentq, milp, LinearConstraint, Bounds

st.set_page_config(page_title="Quant Pool Engine", layout="wide")
st.title("🧠 Quant Pool Engine – Shin, Logit & MILP-Optimering")
st.markdown(
    "Matematiskt validerad motor med **Shin De-vigging**, **Log-Odds Ensemble** och **Linjär Programmering (SciPy HiGHS MILP)**."
)

# --- 1. SIDOMENY & INSTÄLLNINGAR ---
product_map = {
    "Powerplay (8 matcher)": ("powerplay", 8, 0.70),
    "Topptipset (8 matcher)": ("topptipset", 8, 0.70),
    "Stryktipset (13 matcher)": ("stryktipset", 13, 0.28),
    "Europatipset (13 matcher)": ("europatipset", 13, 0.28),
}
selected_label = st.sidebar.selectbox("1. Välj spelform", list(product_map.keys()))
product, expected_matches, pool_share = product_map[selected_label]
export_name = selected_label.split(" ")[0]

st.sidebar.divider()
st.sidebar.subheader("💰 2. Budget & Insats")
max_budget = st.sidebar.number_input("Total budget (kr)", min_value=10, max_value=5000, value=150, step=10)

if product in ["stryktipset", "europatipset"]:
    stake_per_row = 1
    st.sidebar.caption("ℹ️ Radinsats på 13-matchersspel är fast på 1 kr.")
else:
    stake_per_row = st.sidebar.selectbox("Insats per rad (kr)", [1, 2, 5, 10], index=0)

strategy = st.sidebar.selectbox(
    "3. Optimeringsmål (MILP)",
    [
        "Optimal EV (Maximerar Log-Utility: Vinstchans x Utdelningsproxy)",
        "Trygg & Säker (Maximerar exakt gemensam sannolikhet för full pott)",
        "Skrälljägare (Maximerar positiv Edge & rensarpotential)",
    ],
)

min_sign_quota = st.sidebar.slider(
    "Minsta teckentäckning i garderingar (%)",
    min_value=10,
    max_value=30,
    value=20,
    help="Garanterar via linjär programmering att inget garderad tecken raderas vid reduceringen.",
) / 100.0


# --- 2. ROBUST DATAINHÄMTNING & VALIDERING ---
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
                    sr = requests.get(s_url, headers=headers, timeout=5)
                    if sr.status_code == 200:
                        d["_extra_stats"] = sr.json().get("statistics", {})
                except Exception:
                    d["_extra_stats"] = {}
        return draws_list
    except Exception as e:
        st.error(f"Nätverksfel mot Svenska Spels API: {e}")
        return []


def safe_float(val):
    if val is None or val == "":
        return None
    try:
        v = float(str(val).replace(",", "."))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def safe_int(val):
    if val is None or val == "":
        return None
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


def parse_form_points(form_raw):
    if not form_raw:
        return None
    seq = []
    if isinstance(form_raw, str):
        seq = list(form_raw.strip().upper())
    elif isinstance(form_raw, list):
        for item in form_raw:
            if isinstance(item, dict):
                val = item.get("outcome") or item.get("result") or ""
                seq.append(str(val).upper())
            elif item is not None:
                seq.append(str(item).upper())
    if not seq:
        return None
    pts = 0
    valid_matches = 0
    for ch in seq[-5:]:
        if any(w in ch for w in ["W", "V", "WIN", "3"]):
            pts += 3
            valid_matches += 1
        elif any(d in ch for d in ["D", "O", "X", "DRAW", "1"]):
            pts += 1
            valid_matches += 1
        elif any(l in ch for l in ["L", "F", "LOSS", "0"]):
            valid_matches += 1
    return pts if valid_matches > 0 else None


def extract_verified_metadata(ev, extra_ev):
    """Extraherar validerad tabell, form och matchtyp utan gissningar."""
    h_rank, a_rank, h_form, a_form = None, None, None, None
    event_type = ev.get("eventTypeDescription") or ev.get("eventType") or "Match"

    match_obj = ev.get("match") or {}
    for p in match_obj.get("participants", []):
        if not isinstance(p, dict):
            continue
        t_type = str(p.get("type", "")).lower()
        r_val = safe_int(p.get("ranking") or p.get("tablePosition"))
        f_val = parse_form_points(p.get("form") or p.get("trend"))
        if "home" in t_type:
            h_rank = r_val if r_val is not None else h_rank
            h_form = f_val if f_val is not None else h_form
        elif "away" in t_type:
            a_rank = r_val if a_rank is not None else a_rank
            a_form = f_val if f_val is not None else a_form

    if isinstance(extra_ev, dict):
        standings = extra_ev.get("standings") or extra_ev.get("table") or []
        for row in standings:
            if not isinstance(row, dict):
                continue
            pos = safe_int(row.get("position") or row.get("rank"))
            if row.get("isHomeTeam") or row.get("teamType") == "home":
                h_rank = h_rank if h_rank is not None else pos
            elif row.get("isAwayTeam") or row.get("teamType") == "away":
                a_rank = a_rank if a_rank is not None else pos

        hf_ex = parse_form_points(extra_ev.get("homeForm") or extra_ev.get("formHome"))
        af_ex = parse_form_points(extra_ev.get("awayForm") or extra_ev.get("formAway"))
        h_form = h_form if h_form is not None else hf_ex
        a_form = a_form if a_form is not None else af_ex

    info_parts = []
    if h_rank is not None and a_rank is not None:
        info_parts.append(f"Tabell: #{h_rank} vs #{a_rank}")
    if h_form is not None and a_form is not None:
        info_parts.append(f"Form(5): {h_form}p vs {a_form}p")

    return h_rank, a_rank, h_form, a_form, event_type, " | ".join(info_parts)


def compute_shin_probabilities(o1, ox, o2):
    """Exakt Shin (1993) de-vigging löst direkt med SciPy brentq (inga externa kompileringskrav)."""
    if o1 and ox and o2 and o1 > 1.0 and ox > 1.0 and o2 > 1.0:
        inv = np.array([1.0 / o1, 1.0 / ox, 1.0 / o2], dtype=np.float64)
        S = float(np.sum(inv))
        if S <= 1.0001:
            return inv / S
        try:
            def shin_obj(z):
                p = (np.sqrt(z**2 + 4.0 * (1.0 - z) * (inv**2) / S) - z) / (2.0 * (1.0 - z))
                return float(np.sum(p) - 1.0)

            z_opt = brentq(shin_obj, 1e-9, 0.999)
            p_arr = (np.sqrt(z_opt**2 + 4.0 * (1.0 - z_opt) * (inv**2) / S) - z_opt) / (2.0 * (1.0 - z_opt))
            if np.all(np.isfinite(p_arr)) and np.all(p_arr > 0):
                return p_arr / np.sum(p_arr)
        except Exception:
            pass
        return inv / S
    return None


draws = fetch_draws(product)
if not draws:
    st.warning("Ingen öppen omgång hittades just nu.")
    st.stop()

draw_options = {f"Omgång {d.get('drawNumber')} - {d.get('drawComment', '')}": d for d in draws}
selected_key = st.sidebar.selectbox("Välj omgång", list(draw_options.keys()))
draw = draw_options[selected_key]
draw_number = draw.get("drawNumber")

if st.sidebar.button("🔄 Uppdatera live-data"):
    st.cache_data.clear()
    st.rerun()

events = draw.get("drawEvents", [])
if len(events) != expected_matches:
    st.error(f"Felaktigt antal matcher i API-svaret ({len(events)} st, förväntade {expected_matches} st).")
    st.stop()

extra_stats_obj = draw.get("_extra_stats") or {}
extra_events_list = extra_stats_obj.get("events") or extra_stats_obj.get("drawEvents") or []
extra_map = {ev.get("eventNumber"): ev for ev in extra_events_list if isinstance(ev, dict)}


# --- 3. KALIBRERAD SANNOLIKHETSMODELL (SHIN + LOGIT ENSEMBLE) ---
match_data = []
missing_odds_warnings = []
missing_folk_warnings = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    ex = extra_map.get(num, {})

    sf = ev.get("svenskaFolket") or ex.get("svenskaFolket") or {}
    s1_raw, sx_raw, s2_raw = safe_float(sf.get("one")), safe_float(sf.get("x")), safe_float(sf.get("two"))
    if s1_raw is not None and sx_raw is not None and s2_raw is not None and (s1_raw + sx_raw + s2_raw) > 0:
        s_vec = np.array([s1_raw, sx_raw, s2_raw], dtype=np.float64)
        s_vec = np.clip(s_vec, 0.5, 99.0)
        s_probs = s_vec / np.sum(s_vec)
    else:
        s_probs = np.array([1 / 3, 1 / 3, 1 / 3], dtype=np.float64)
        missing_folk_warnings.append(num)

    odds = ev.get("odds") or ex.get("odds") or {}
    o1, ox, o2 = safe_float(odds.get("one")), safe_float(odds.get("x")), safe_float(odds.get("two"))
    shin_probs = compute_shin_probabilities(o1, ox, o2)

    if shin_probs is None:
        missing_odds_warnings.append(num)
        base_probs = s_probs.copy()
        odds_source = "Streck (Odds saknas)"
    else:
        base_probs = shin_probs
        odds_source = f"Shin ({o1:.2f}-{ox:.2f}-{o2:.2f})"

    tt = ev.get("tioTidningarsTips") or ev.get("newspaperAdvice") or ex.get("tioTidningarsTips") or {}
    tt1, ttx, tt2 = safe_int(tt.get("one")) or 0, safe_int(tt.get("x")) or 0, safe_int(tt.get("two")) or 0
    tt_sum = tt1 + ttx + tt2

    h_r, a_r, h_f, a_f, ev_type, stat_str = extract_verified_metadata(ev, ex)

    logits = np.log(np.clip(base_probs, 1e-4, 1.0))

    if tt_sum >= 5:
        tt_smoothed = np.array([tt1 + 0.5, ttx + 0.5, tt2 + 0.5]) / (tt_sum + 1.5)
        logits = 0.92 * logits + 0.08 * np.log(tt_smoothed)

    if h_r is not None and a_r is not None:
        rank_signal = np.clip((a_r - h_r) / 20.0, -1.0, 1.0) * 0.06
        logits[0] += rank_signal
        logits[2] -= rank_signal

    if h_f is not None and a_f is not None:
        form_signal = np.clip((h_f - a_f) / 15.0, -1.0, 1.0) * 0.05
        logits[0] += form_signal
        logits[2] -= form_signal

    model_probs = softmax(logits)
    edges = (model_probs - s_probs) * 100.0
    ev_ratios = model_probs / np.clip(s_probs, 0.005, 1.0)

    match_data.append({
        "Nr": num,
        "Match": desc,
        "Källa": f"{odds_source}" + (f" | {stat_str}" if stat_str else ""),
        "s1": s_probs[0] * 100, "sx": s_probs[1] * 100, "s2": s_probs[2] * 100,
        "p1": model_probs[0] * 100, "px": model_probs[1] * 100, "p2": model_probs[2] * 100,
        "v1": edges[0], "vx": edges[1], "v2": edges[2],
        "p_vec": model_probs,
        "s_vec": s_probs,
        "ev_vec": ev_ratios,
        "tt_str": f"{tt1}-{ttx}-{tt2}" if tt_sum > 0 else "Ej släppt",
    })

if missing_odds_warnings:
    st.warning(f"⚠️ Marknadsodds saknas för match {missing_odds_warnings}. Modellen faller tillbaka på streckfördelning.")
if missing_folk_warnings:
    st.warning(f"⚠️ Streckfördelning saknas för match {missing_folk_warnings}. Antagit likafördelning (33.3%).")


# --- 4. MATEMATISKT MOTIVERAD RAM-ALLOKERING ---
allowed_max_rows = max(int(max_budget / stake_per_row), 1)
is_safe = strategy.startswith("Trygg")
is_hunter = strategy.startswith("Skräll")

if expected_matches == 13:
    if allowed_max_rows <= 64:
        t_spik, t_halv = 6, 4
    elif allowed_max_rows <= 160:
        t_spik, t_halv = 5, 4
    elif allowed_max_rows <= 350:
        t_spik, t_halv = 4, 5
    else:
        t_spik, t_halv = 4, 4
else:
    if allowed_max_rows <= 48:
        t_spik, t_halv = 3, 3
    elif allowed_max_rows <= 160:
        t_spik, t_halv = 2, 3
    else:
        t_spik, t_halv = 1, 3

spik_scores = []
for i, m in enumerate(match_data):
    p_v = m["p_vec"]
    s_v = m["s_vec"]
    edges_v = (p_v - s_v) * 100.0
    signs = ["1", "X", "2"]

    if is_safe:
        best_i = int(np.argmax(p_v))
        score = float(p_v[best_i] * 100.0)
    elif is_hunter:
        valid_cands = [idx for idx in range(3) if p_v[idx] >= 0.35] or [int(np.argmax(p_v))]
        best_i = max(valid_cands, key=lambda idx: p_v[idx] * 100.0 + edges_v[idx] * 1.5)
        score = float(p_v[best_i] * 100.0 + edges_v[best_i] * 1.5)
    else:
        best_i = int(np.argmax(p_v))
        score = float(p_v[best_i] * 100.0 + edges_v[best_i] * 0.75)

    spik_scores.append((i, signs[best_i], score))

ranked_matches = sorted(spik_scores, key=lambda x: x[2], reverse=True)
spik_map = {idx: s_char for idx, s_char, _ in ranked_matches[:t_spik]}
halv_set = {idx for idx, _, _ in ranked_matches[t_spik : t_spik + t_halv]}

selections, roles, explanations = [], [], []
sign_labels = ["1", "X", "2"]

for i, m in enumerate(match_data):
    p_v, s_v = m["p_vec"], m["s_vec"]
    e_v = (p_v - s_v) * 100.0

    if i in spik_map:
        s_char = spik_map[i]
        s_idx = sign_labels.index(s_char)
        selections.append([s_char])
        roles.append("🔒 Spik")
        explanations.append(
            f"Spik {s_char}: {p_v[s_idx]*100:.1f}% sannolikhet (Edge: {e_v[s_idx]:+.1f}%)"
        )
    elif i in halv_set:
        pairs = [(0, 1), (1, 2), (0, 2)]
        if is_safe:
            best_pair = max(pairs, key=lambda pr: p_v[pr[0]] + p_v[pr[1]])
        elif is_hunter:
            best_pair = max(pairs, key=lambda pr: (p_v[pr[0]] + p_v[pr[1]]) * 100 + (e_v[pr[0]] + e_v[pr[1]]) * 1.2)
        else:
            best_pair = max(pairs, key=lambda pr: (p_v[pr[0]] + p_v[pr[1]]) * 100 + (e_v[pr[0]] + e_v[pr[1]]) * 0.5)

        chosen = [sign_labels[best_pair[0]], sign_labels[best_pair[1]]]
        cov_prob = (p_v[best_pair[0]] + p_v[best_pair[1]]) * 100.0
        selections.append(chosen)
        roles.append("🛡️ Halvgardering")
        explanations.append(f"Låser {''.join(chosen)} (Täcker {cov_prob:.1f}% av sannolikheten)")
    else:
        selections.append(["1", "X", "2"])
        roles.append("💣 Helgardering")
        best_e_idx = int(np.argmax(e_v))
        explanations.append(
            f"Helgarderad (Bästa värdetecken: '{sign_labels[best_e_idx]}' med {e_v[best_e_idx]:+.1f}% Edge)"
        )


# --- 5. EXAKT RADOPTIMERING MED SCIPY MILP (HiGHS) & SANN RADSANNOLIKHET ---
all_rows = list(itertools.product(*selections))
num_ram_rows = len(all_rows)
target_k = min(allowed_max_rows, num_ram_rows)

sign_to_idx = {"1": 0, "X": 1, "2": 2}
r_idx = np.array([[sign_to_idx[s] for s in r] for r in all_rows], dtype=np.int32)

p_mat = np.array([m["p_vec"] for m in match_data], dtype=np.float64)
s_mat = np.array([m["s_vec"] for m in match_data], dtype=np.float64)

m_arange = np.arange(expected_matches)
row_p_matrix = p_mat[m_arange, r_idx]
row_s_matrix = s_mat[m_arange, r_idx]

joint_row_probs = np.prod(row_p_matrix, axis=1)
joint_folk_probs = np.prod(row_s_matrix, axis=1)

payout_proxies = (pool_share / np.clip(joint_folk_probs, 1e-12, 1.0)) * stake_per_row
ev_indices = joint_row_probs * (pool_share / np.clip(joint_folk_probs, 1e-12, 1.0))

if is_safe:
    obj_weights = joint_row_probs * 1e6
elif is_hunter:
    obj_weights = (joint_row_probs ** 0.65) * (ev_indices ** 0.60) * 1e6
else:
    obj_weights = (joint_row_probs ** 0.85) * (ev_indices ** 0.35) * 1e6

# Bygg MILP-tvång med SciPy HiGHS (snabb C-implementerad lösare inbyggd i SciPy)
A_rows = [np.ones(num_ram_rows, dtype=np.float64)]
lb_list = [float(target_k)]
ub_list = [float(target_k)]

for m_i, signs in enumerate(selections):
    if len(signs) > 1:
        quota_rows = max(1, int(np.floor(target_k * min_sign_quota)))
        max_feasible = int(np.floor(target_k / len(signs)))
        req_count = min(quota_rows, max_feasible)
        for s_char in signs:
            s_code = sign_to_idx[s_char]
            indicator = (r_idx[:, m_i] == s_code).astype(np.float64)
            if np.sum(indicator) >= req_count:
                A_rows.append(indicator)
                lb_list.append(float(req_count))
                ub_list.append(float(target_k))

A_matrix = np.vstack(A_rows)
constraints =
