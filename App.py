import streamlit as st
import requests
import pandas as pd
import numpy as np
import itertools
from datetime import datetime, timezone
from scipy.special import softmax
from scipy.optimize import brentq, milp, LinearConstraint, Bounds

st.set_page_config(page_title="Quant Pool Engine", layout="wide")
st.title("🧠 Quant Pool Engine – Shin, Logit & MILP")
st.markdown(
    "Matematiskt reviderad kupongmotor med **Shin De-vigging**, **Logit-justering** och **SciPy HiGHS MILP**."
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
    "3. Optimeringsmål",
    [
        "Balanserad heuristik (Viktad sannolikhets- och streckvärdespoäng)",
        "Trygg & Säker – Obegränsad ( Globalt högsta gemensamma sannolikhet)",
        "Trygg & Säker – Ram & Kvot (Högsta sannolikhet inom ram & täckningskrav)",
        "Skrälljägare (Heuristik med hög vikt på relativt streckvärde)",
    ],
)

min_sign_quota = st.sidebar.slider(
    "Minsta teckentäckning i garderingar (%)",
    min_value=10,
    max_value=30,
    value=20,
    help="Använder ceil(K * kvot) i MILP-lösaren. Gäller ej vid 'Trygg & Säker – Obegränsad'.",
) / 100.0


# --- 2. STRIKT PARSING & DATAINHÄMTNING ---
def parse_valid_odd(val):
    if val is None or val == "":
        return None
    try:
        v = float(str(val).replace(",", "."))
        return v if (np.isfinite(v) and v > 1.0) else None
    except (ValueError, TypeError):
        return None


def parse_valid_pct(val):
    if val is None or val == "":
        return None
    try:
        v = float(str(val).replace(",", "."))
        return v if (np.isfinite(v) and 0.0 <= v <= 100.0) else None
    except (ValueError, TypeError):
        return None


def parse_valid_int(val):
    if val is None or val == "":
        return None
    try:
        f = float(str(val))
        return int(f) if np.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def parse_form_points(form_raw):
    """Exakt token-matchning (undviker 'W' i 'DRAW' och 'O' i 'LOSS')."""
    if not form_raw:
        return None
    tokens = []
    if isinstance(form_raw, str):
        cleaned = form_raw.strip().upper()
        if any(sep in cleaned for sep in [",", " ", "-", "|"]):
            tokens = [t.strip() for t in cleaned.replace(",", " ").replace("-", " ").replace("|", " ").split() if t.strip()]
        elif cleaned in {"WIN", "DRAW", "LOSS", "W", "D", "L", "V", "O", "F"}:
            tokens = [cleaned]
        else:
            tokens = list(cleaned)
    elif isinstance(form_raw, list):
        for item in form_raw:
            if isinstance(item, dict):
                val = item.get("outcome") or item.get("result") or ""
                if isinstance(val, str) and val.strip():
                    tokens.append(val.strip().upper())
            elif isinstance(item, str) and item.strip():
                tokens.append(item.strip().upper())

    win_tokens = {"W", "V", "WIN", "WON"}
    draw_tokens = {"D", "O", "X", "DRAW", "TIED"}
    loss_tokens = {"L", "F", "LOSS", "LOST"}

    pts, valid_cnt = 0, 0
    for tok in tokens[-5:]:
        if tok in win_tokens:
            pts += 3
            valid_cnt += 1
        elif tok in draw_tokens:
            pts += 1
            valid_cnt += 1
        elif tok in loss_tokens:
            valid_cnt += 1
    return pts if valid_cnt > 0 else None


def extract_event_odds(ev, extra_ev):
    """Läser primära odds eller fallbackar till betMetrics.values (t.ex. för Powerplay H2H)."""
    odds_obj = ev.get("odds") or (extra_ev.get("odds") if isinstance(extra_ev, dict) else None) or {}
    o1 = parse_valid_odd(odds_obj.get("one"))
    ox = parse_valid_odd(odds_obj.get("x"))
    o2 = parse_valid_odd(odds_obj.get("two"))
    if o1 and ox and o2:
        return o1, ox, o2, "Odds"

    # Fallback: betMetrics -> values (används ofta för H2H-spelardueller i Powerplay)
    for src in (ev, extra_ev if isinstance(extra_ev, dict) else {}):
        bm = src.get("betMetrics") or {}
        values = bm.get("values") or []
        if isinstance(values, list) and len(values) >= 3:
            found = {}
            for idx, item in enumerate(values):
                if not isinstance(item, dict):
                    continue
                out_key = str(item.get("outcome") or item.get("id") or "").upper()
                nested_odds = item.get("odds")
                raw_o = nested_odds.get("odds") if isinstance(nested_odds, dict) else nested_odds
                parsed_o = parse_valid_odd(raw_o)
                if out_key in {"1", "ONE", "HOME"}:
                    found["1"] = parsed_o
                elif out_key in {"X", "DRAW", "TIE"}:
                    found["X"] = parsed_o
                elif out_key in {"2", "TWO", "AWAY"}:
                    found["2"] = parsed_o
                elif idx < 3 and parsed_o is not None:
                    found[["1", "X", "2"][idx]] = parsed_o
            if found.get("1") and found.get("X") and found.get("2"):
                return found["1"], found["X"], found["2"], "betMetrics"

    return None, None, None, None


def extract_event_folket(ev, extra_ev):
    """Läser svenskaFolket eller fallbackar till betMetrics distribution."""
    sf = ev.get("svenskaFolket") or (extra_ev.get("svenskaFolket") if isinstance(extra_ev, dict) else None) or {}
    s1 = parse_valid_pct(sf.get("one"))
    sx = parse_valid_pct(sf.get("x"))
    s2 = parse_valid_pct(sf.get("two"))
    if s1 is not None and sx is not None and s2 is not None and (s1 + sx + s2) > 0:
        return np.array([s1, sx, s2], dtype=np.float64)

    for src in (ev, extra_ev if isinstance(extra_ev, dict) else {}):
        bm = src.get("betMetrics") or {}
        values = bm.get("values") or []
        if isinstance(values, list) and len(values) >= 3:
            dist = []
            for item in values[:3]:
                if isinstance(item, dict):
                    d_obj = item.get("distribution")
                    raw_d = d_obj.get("distribution") if isinstance(d_obj, dict) else d_obj
                    dist.append(parse_valid_pct(raw_d))
            if len(dist) == 3 and all(d is not None for d in dist) and sum(dist) > 0:
                return np.array(dist, dtype=np.float64)
    return None


def detect_player_h2h(ev):
    """Identifierar spelar-H2H via verifierad API-metadata istället för regex/streck."""
    ev_type = str(ev.get("eventTypeDescription") or ev.get("eventType") or "").lower()
    if any(k in ev_type for k in ["head", "h2h", "duell", "spelare", "player"]):
        return True
    match_obj = ev.get("match") or {}
    m_type = str(match_obj.get("matchType") or match_obj.get("type") or "").lower()
    if any(k in m_type for k in ["head", "h2h", "duell", "player"]):
        return True
    if ev.get("odds") is None and isinstance(ev.get("betMetrics"), dict):
        return True
    return False


def extract_verified_metadata(ev, extra_ev):
    is_h2h = detect_player_h2h(ev)
    if is_h2h:
        return None, None, None, None, True, "Spelarduell (H2H)"

    h_rank, a_rank, h_form, a_form = None, None, None, None
    match_obj = ev.get("match") or {}
    for p in match_obj.get("participants", []):
        if not isinstance(p, dict):
            continue
        t_type = str(p.get("type", "")).lower()
        r_val = parse_valid_int(p.get("ranking") or p.get("tablePosition"))
        f_val = parse_form_points(p.get("form") or p.get("trend"))
        if "home" in t_type:
            h_rank = r_val if (r_val is not None and r_val > 0) else h_rank
            h_form = f_val if f_val is not None else h_form
        elif "away" in t_type:
            a_rank = r_val if (r_val is not None and r_val > 0) else a_rank
            a_form = f_val if f_val is not None else a_form

    if isinstance(extra_ev, dict):
        for row in (extra_ev.get("standings") or extra_ev.get("table") or []):
            if not isinstance(row, dict):
                continue
            pos = parse_valid_int(row.get("position") or row.get("rank"))
            if pos is not None and pos > 0:
                if row.get("isHomeTeam") or row.get("teamType") == "home":
                    h_rank = h_rank if h_rank is not None else pos
                elif row.get("isAwayTeam") or row.get("teamType") == "away":
                    a_rank = a_rank if a_rank is not None else pos
        hf_ex = parse_form_points(extra_ev.get("homeForm") or extra_ev.get("formHome"))
        af_ex = parse_form_points(extra_ev.get("awayForm") or extra_ev.get("formAway"))
        h_form = h_form if h_form is not None else hf_ex
        a_form = a_form if a_form is not None else af_ex

    info = []
    if h_rank is not None and a_rank is not None:
        info.append(f"Tabell: #{h_rank} vs #{a_rank}")
    if h_form is not None and a_form is not None:
        info.append(f"Form(5): {h_form}p vs {a_form}p")
    return h_rank, a_rank, h_form, a_form, False, " | ".join(info)


def compute_shin_probabilities(o1, ox, o2):
    if o1 and ox and o2:
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


@st.cache_data(ttl=120)
def fetch_open_draws(prod):
    url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        raw_draws = r.json().get("draws", [])
        open_draws = []
        for d in raw_draws:
            state = str(d.get("drawState") or "").lower()
            if state and state not in {"open", "active", "10"}:
                continue
            d_num = d.get("drawNumber")
            if d_num:
                try:
                    s_url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws/{d_num}/statistics"
                    sr = requests.get(s_url, headers=headers, timeout=5)
                    d["_extra_stats"] = sr.json().get("statistics", {}) if sr.status_code == 200 else {}
                except Exception:
                    d["_extra_stats"] = {}
            open_draws.append(d)
        return open_draws
    except Exception as e:
        st.error(f"Nätverksfel mot Svenska Spels API: {e}")
        return []


draws = fetch_open_draws(product)
if not draws:
    st.warning("Ingen öppen omgång hittades just nu.")
    st.stop()

draw_options = {
    f"Omgång {d.get('drawNumber')} ({d.get('drawState', 'Okänd')}) - {d.get('drawComment', '')}": d
    for d in draws
}
selected_key = st.sidebar.selectbox("Välj omgång", list(draw_options.keys()))
draw = draw_options[selected_key]
draw_number = draw.get("drawNumber")
close_time_str = draw.get("regCloseTime")

if close_time_str:
    try:
        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        if close_dt < datetime.now(timezone.utc):
            st.warning(f"⚠️ Spelstopp för denna omgång ({close_time_str}) har redan passerat.")
    except Exception:
        pass

if st.sidebar.button("🔄 Uppdatera live-data"):
    st.cache_data.clear()
    st.rerun()

events = draw.get("drawEvents", [])
if len(events) != expected_matches:
    st.error(f"Felaktigt antal matcher ({len(events)} st, förväntade {expected_matches} st).")
    st.stop()

extra_stats_obj = draw.get("_extra_stats") or {}
extra_events_list = extra_stats_obj.get("events") or extra_stats_obj.get("drawEvents") or []
extra_map = {ev.get("eventNumber"): ev for ev in extra_events_list if isinstance(ev, dict)}


# --- 3. SANNOLIKHETSMODELL & HANTERING AV SAKNAD DATA ---
match_data = []
missing_odds_matches = []
missing_folk_matches = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    ex = extra_map.get(num, {})

    raw_folk_vec = extract_event_folket(ev, ex)
    if raw_folk_vec is not None:
        s_probs = raw_folk_vec / np.sum(raw_folk_vec)
        has_folket = True
    else:
        s_probs = None
        has_folket = False
        missing_folk_matches.append(num)

    o1, ox, o2, odds_src_label = extract_event_odds(ev, ex)
    shin_probs = compute_shin_probabilities(o1, ox, o2)

    if shin_probs is not None:
        base_probs = shin_probs
        odds_source = f"Shin/{odds_src_label} ({o1:.2f}-{ox:.2f}-{o2:.2f})"
    elif s_probs is not None:
        missing_odds_matches.append(num)
        base_probs = np.clip(s_probs, 1e-3, 1.0)
        base_probs = base_probs / np.sum(base_probs)
        odds_source = "Streck (Odds saknas)"
    else:
        st.error(f"Match {num} ({desc}) saknar både odds och streckfördelning. Kan ej beräkna kupong.")
        st.stop()

    tt = ev.get("tioTidningarsTips") or ev.get("newspaperAdvice") or ex.get("tioTidningarsTips") or {}
    tt1 = parse_valid_int(tt.get("one")) or 0
    ttx = parse_valid_int(tt.get("x")) or 0
    tt2 = parse_valid_int(tt.get("two")) or 0
    tt_sum = tt1 + ttx + tt2

    h_r, a_r, h_f, a_f, is_h2h, stat_str = extract_verified_metadata(ev, ex)
    logits = np.log(np.clip(base_probs, 1e-4, 1.0))

    # Applicera endast TT/Tabell/Form om det INTE är en spelar-H2H
    if not is_h2h:
        if tt_sum >= 5:
            tt_sm = np.array([tt1 + 0.5, ttx + 0.5, tt2 + 0.5]) / (tt_sum + 1.5)
            logits = 0.92 * logits + 0.08 * np.log(tt_sm)
        if h_r is not None and a_r is not None:
            r_sig = np.clip((a_r - h_r) / 20.0, -1.0, 1.0) * 0.06
            logits[0] += r_sig
            logits[2] -= r_sig
        if h_f is not None and a_f is not None:
            f_sig = np.clip((h_f - a_f) / 15.0, -1.0, 1.0) * 0.05
            logits[0] += f_sig
            logits[2] -= f_sig

    model_probs = softmax(logits)

    if has_folket:
        edges = (model_probs - s_probs) * 100.0
    else:
        edges = np.zeros(3, dtype=np.float64)

    match_data.append({
        "Nr": num,
        "Match": desc,
        "Källa": f"{odds_source}" + (f" | {stat_str}" if stat_str else ""),
        "has_folket": has_folket,
        "s1": s_probs[0] * 100 if has_folket else None,
        "sx": s_probs[1] * 100 if has_folket else None,
        "s2": s_probs[2] * 100 if has_folket else None,
        "p1": model_probs[0] * 100,
        "px": model_probs[1] * 100,
        "p2": model_probs[2] * 100,
        "v1": edges[0],
        "vx": edges[1],
        "v2": edges[2],
        "p_vec": model_probs,
        "s_vec": s_probs,
    })

all_have_folket = len(missing_folk_matches) == 0

if missing_odds_matches:
    st.warning(f"⚠️ Marknadsodds saknas för match {missing_odds_matches}. Använder streck som bas.")
if not all_have_folket:
    st.warning(
        f"⚠️ Streckfördelning saknas för match {missing_folk_matches}. "
        "Värde-/Edge-optimering är inaktiverad för att förhindra artificiellt värde (optimerar enbart på sannolikhet)."
    )

allowed_max_rows = max(int(max_budget / stake_per_row), 1)
is_unconstrained_safe = strategy.startswith("Trygg & Säker – Obegränsad")
is_framed_safe = strategy.startswith("Trygg & Säker – Ram")
is_safe = is_unconstrained_safe or is_framed_safe or (not all_have_folket)
is_hunter = strategy.startswith("Skräll") and all_have_folket


# --- 4. URVAL AV RADER (OBEGRÄNSAD SANNOLIKHET ELLER RAM + MILP) ---
signs_list = ["1", "X", "2"]
sign_to_idx = {"1": 0, "X": 1, "2": 2}
p_mat = np.array([m["p_vec"] for m in match_data], dtype=np.float64)
s_mat = (
    np.array([np.clip(m["s_vec"], 1e-4, 1.0) for m in match_data], dtype=np.float64)
    if all_have_folket
    else None
)

if is_unconstrained_safe:
    # Globalt obegränsad maximering av gemensam sannolikhet (k-kortaste vägar / top-K produkter)
    beam = [(1.0, ())]
    for m_i in range(expected_matches):
        next_beam = []
        for prob_so_far, seq in beam:
            for s_i in range(3):
                next_beam.append((prob_so_far * float(p_mat[m_i, s_i]), seq + (s_i,)))
        next_beam.sort(key=lambda x: x[0], reverse=True)
        beam = next_beam[:allowed_max_rows]

    r_idx = np.array([seq for _, seq in beam], dtype=np.int32)
    filtered_rows = [tuple(signs_list[c] for c in seq) for _, seq in beam]
    selected_idx = list(range(len(filtered_rows)))
    sel_probs = np.array([pr for pr, _ in beam], dtype=np.float64)
    num_ram_rows = 3**expected_matches
    solver_status_str = "✅ Globalt optimal (Top-K högsta gemensamma sannolikhet utan rambegränsning)"

    # Härled faktisk teckenomfattning per match i den valda portföljen
    selections, roles, explanations = [], [], []
    for i in range(expected_matches):
        used_codes = sorted(set(r_idx[:, i]))
        used_chars = [signs_list[c] for c in used_codes]
        selections.append(used_chars)
        roles.append("🔒 Spik" if len(used_chars) == 1 else ("🛡️ Halv" if len(used_chars) == 2 else "💣 Hel"))
        explanations.append("Globalt sannolikhetsstyrt urval")
    t_spik = sum(1 for s in selections if len(s) == 1)
    t_halv = sum(1 for s in selections if len(s) == 2)

else:
    # Ram-allokering + SciPy HiGHS MILP med ceil-kvot
    if expected_matches == 13:
        t_spik, t_halv = (
            (6, 4) if allowed_max_rows <= 64 else ((5, 4) if allowed_max_rows <= 160 else ((4, 5) if allowed_max_rows <= 350 else (4, 4)))
        )
    else:
        t_spik, t_halv = (3, 3) if allowed_max_rows <= 48 else ((2, 3) if allowed_max_rows <= 160 else (1, 3))

    spik_scores = []
    for i, m in enumerate(match_data):
        p_v = m["p_vec"]
        edges_v = np.array([m["v1"], m["vx"], m["v2"]], dtype=np.float64)
        if is_safe:
            best_i = int(np.argmax(p_v))
            sc = float(p_v[best_i] * 100.0)
        elif is_hunter:
            cands = [idx for idx in range(3) if p_v[idx] >= 0.35] or [int(np.argmax(p_v))]
            best_i = max(cands, key=lambda idx: p_v[idx] * 100.0 + edges_v[idx] * 1.5)
            sc = float(p_v[best_i] * 100.0 + edges_v[best_i] * 1.5)
        else:
            best_i = int(np.argmax(p_v))
            sc = float(p_v[best_i] * 100.0 + edges_v[best_i] * 0.75)
        spik_scores.append((i, signs_list[best_i], sc))

    ranked_matches = sorted(spik_scores, key=lambda x: x[2], reverse=True)
    spik_map = {idx: s_ch for idx, s_ch, _ in ranked_matches[:t_spik]}
    halv_set = {idx for idx, _, _ in ranked_matches[t_spik : t_spik + t_halv]}

    selections, roles, explanations = [], [], []
    for i, m in enumerate(match_data):
        p_v = m["p_vec"]
        e_v = np.array([m["v1"], m["vx"], m["v2"]], dtype=np.float64)
        if i in spik_map:
            s_ch = spik_map[i]
            s_ix = signs_list.index(s_ch)
            selections.append([s_ch])
            roles.append("🔒 Spik")
            explanations.append(f"Spik {s_ch}: {p_v[s_ix]*100:.1f}% chans")
        elif i in halv_set:
            pairs = [(0, 1), (1, 2), (0, 2)]
            w_e = 0.0 if is_safe else (1.2 if is_hunter else 0.5)
            best_p = max(pairs, key=lambda pr: (p_v[pr[0]] + p_v[pr[1]]) * 100 + (e_v[pr[0]] + e_v[pr[1]]) * w_e)
            chosen = [signs_list[best_p[0]], signs_list[best_p[1]]]
            cov = (p_v[best_p[0]] + p_v[best_p[1]]) * 100.0
            selections.append(chosen)
            roles.append("🛡️ Halvgardering")
            explanations.append(f"Låser {''.join(chosen)} ({cov:.1f}% sannolikhet)")
        else:
            selections.append(["1", "X", "2"])
            roles.append("💣 Helgardering")
            b_ix = int(np.argmax(e_v))
            explanations.append(f"Helgarderad (Högst diff: '{signs_list[b_ix]}' {e_v[b_ix]:+.1f}%)")

    all_rows = list(itertools.product(*selections))
    num_ram_rows = len(all_rows)
    target_k = min(allowed_max_rows, num_ram_rows)

    r_idx = np.array([[sign_to_idx[s] for s in r] for r in all_rows], dtype=np.int32)
    m_arange = np.arange(expected_matches)
    joint_row_probs = np.prod(p_mat[m_arange, r_idx], axis=1)

    if all_have_folket:
        joint_folk_probs = np.prod(s_mat[m_arange, r_idx], axis=1)
        rel_val_scores = joint_row_probs * (pool_share / np.clip(joint_folk_probs, 1e-12, 1.0))
    else:
        rel_val_scores = np.ones_like(joint_row_probs)

    if is_safe:
        obj_weights = joint_row_probs * 1e6
    elif is_hunter:
        obj_weights = (joint_row_probs**0.65) * (rel_val_scores**0.60) * 1e6
    else:
        obj_weights = (joint_row_probs**0.85) * (rel_val_scores**0.35) * 1e6

    A_rows = [np.ones(num_ram_rows, dtype=np.float64)]
    lb_list, ub_list = [float(target_k)], [float(target_k)]

    for m_i, signs in enumerate(selections):
        if len(signs) > 1:
            # Använder ceil() för äkta minimiprocent
            req = int(np.ceil(target_k * min_sign_quota))
            max_feas = int(np.floor(target_k / len(signs)))
            req_count = min(req, max_feas)
            if req_count >= 1:
                for s_ch in signs:
                    ind = (r_idx[:, m_i] == sign_to_idx[s_ch]).astype(np.float64)
                    if np.sum(ind) >= req_count:
                        A_rows.append(ind)
                        lb_list.append(float(req_count))
                        ub_list.append(float(target_k))

    res = milp(
        c=-obj_weights,
        integrality=np.ones(num_ram_rows),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(np.vstack(A_rows), lb_list, ub_list),
        options={"time_limit": 5.0, "mip_rel_gap": 1e-4},
    )

    if res.success and res.x is not None:
        selected_idx = list(np.where(np.round(res.x) == 1)[0])
        if res.status == 0:
            solver_status_str = "✅ MILP Optimal lösning (Alla täckningskrav uppfyllda)"
        else:
            solver_status_str = f"⚠️ MILP Feasible (Tidsgräns nådd, status={res.status}: {res.message})"
    else:
        selected_idx = []

    if len(selected_idx) != target_k:
        selected_idx = list(np.argsort(obj_weights)[::-1][:target_k])
        solver_status_str = (
            f"🚨 MILP Fallback aktiverad (status={res.status}: {res.message}). "
            "OBS: Täckningskvoterna kunde ej garanteras!"
        )
        st.warning(solver_status_str)

    filtered_rows = [all_rows[i] for i in selected_idx]
    sel_probs = joint_row_probs[selected_idx]
    r_idx = r_idx[selected_idx]


# --- 5. PRESENTATION & TRANSPARENTA NYCKELTAL ---
m_arange = np.arange(expected_matches)
if all_have_folket:
    sel_folk_probs = np.prod(s_mat[m_arange, r_idx], axis=1)
    sel_proxies = (pool_share / np.clip(sel_folk_probs, 1e-12, 1.0)) * stake_per_row
    sel_rel_val = sel_probs * (pool_share / np.clip(sel_folk_probs, 1e-12, 1.0))
else:
    sel_proxies = None
    sel_rel_val = None

st.subheader(f"🎯 Kupongportfölj: {export_name} (Omgång {draw_number})")
st.caption(f"**Optimeringsstatus:** {solver_status_str}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Valda rader", f"{len(filtered_rows)} st", f"Ram: {num_ram_rows:,} rader".replace(",", " "))
c2.metric("Total kostnad", f"{len(filtered_rows) * stake_per_row} kr", f"Spikar: {t_spik} | Halv: {t_halv}")
c3.metric(
    "Modellerad chans till full pott",
    f"{np.sum(sel_probs) * 100:.2f} %",
    "Antar oberoende matcher",
)
if all_have_folket:
    c4.metric(
        "Relativt värdeindex (Medel)",
        f"{np.mean(sel_rel_val):.2f}",
        f"Median utdelningsproxy: ~{int(np.median(sel_proxies)):,} kr".replace(",", " "),
    )
else:
    c4.metric("Relativt värdeindex", "Ej tillgängligt", "Streckdata saknas")

header_line = (
    f"{export_name},Omg={draw_number}"
    if product in ["stryktipset", "europatipset"]
    else f"{export_name},Omg={draw_number},Insats={stake_per_row}"
)
file_content = "\n".join([header_line] + ["E," + ",".join(r) for r in filtered_rows])
st.download_button(
    f"📥 Ladda ner systemfil ({len(filtered_rows) * stake_per_row} kr)",
    data=file_content,
    file_name=f"{product}_omg_{draw_number}.txt",
    mime="text/plain",
    type="primary",
    use_container_width=True,
)

st.divider()
st.subheader("📊 Matchanalys & Faktisk Teckenfördelning i Valda Rader")
table_rows = []
tot_sel = max(len(filtered_rows), 1)

for i, m in enumerate(match_data):
    p1_d = int(round(np.sum(r_idx[:, i] == 0) / tot_sel * 100))
    px_d = int(round(np.sum(r_idx[:, i] == 1) / tot_sel * 100))
    p2_d = int(round(np.sum(r_idx[:, i] == 2) / tot_sel * 100))

    if m["has_folket"]:
        folk_str = f"{m['s1']:.1f}% - {m['sx']:.1f}% - {m['s2']:.1f}%"
        edges = {"1": m["v1"], "X": m["vx"], "2": m["v2"]}
        b_s = max(edges, key=edges.get)
        edge_str = f"{b_s} ({edges[b_s]:+.1f}%)"
    else:
        folk_str = "Saknas"
        edge_str = "N/A"

    row_d = {
        "Match": f"{m['Nr']}. {m['Match']}",
        "Underlag": m["Källa"],
        "Folket (1-X-2)": folk_str,
        "Modell (1-X-2)": f"{m['p1']:.1f}% - {m['px']:.1f}% - {m['p2']:.1f}%",
        "Störst diff": edge_str,
        "Roll": roles[i],
        "Tecken": ", ".join(selections[i]),
        "Andel i rader": f"{p1_d}% / {px_d}% / {p2_d}%",
        "Kommentar": explanations[i],
    }
    table_rows.append(row_d)

st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
