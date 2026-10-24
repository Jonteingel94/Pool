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

# --- 2. HÄMTA ALL DATA + SEPARAT STATISTIK-ENDPOINT FRÅN SVENSKA SPEL ---
@st.cache_data(ttl=120)
def fetch_draws(prod):
    url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        draws_list = r.json().get("draws", [])
        
        # Hämta även detalj- och statistik-endpointen för varje omgång (där TT, tabell och form ofta ligger gömda!)
        for d in draws_list:
            d_num = d.get("drawNumber")
            if d_num:
                try:
                    stat_url = f"https://api.spela.svenskaspel.se/draw/1/{prod}/draws/{d_num}/statistics"
                    sr = requests.get(stat_url, headers=headers, timeout=6)
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

def extract_deep_stats(ev, extra_ev_stat):
    """Dammsuger både huvud-API:et och /statistics-endpointen på tabell, form och TT."""
    h_rank, a_rank = None, None
    h_form_pts, a_form_pts = 0.0, 0.0
    stat_summary = []

    def calc_form_pts(form_raw):
        pts = 0
        if isinstance(form_raw, str) and form_raw:
            for ch in form_raw.upper()[-5:]:
                if ch in ["W", "V", "3"]: pts += 3
                elif ch in ["D", "O", "X", "1"]: pts += 1
        elif isinstance(form_raw, list):
            for item in form_raw[-5:]:
                res = str(item.get("outcome", item) if isinstance(item, dict) else item).upper()
                if res in ["W", "V", "1", "WIN"] or "WIN" in res: pts += 3
                elif res in ["D", "O", "X", "DRAW"] or "DRAW" in res: pts += 1
        return pts

    try:
        # 1. Kolla i match.participants
        match_obj = ev.get("match", {})
        for p in match_obj.get("participants", []):
            t_type = p.get("type", "").lower()
            rank = p.get("ranking") or p.get("tablePosition")
            f_pts = calc_form_pts(p.get("form") or p.get("trend") or "")
            if "home" in t_type:
                if rank: h_rank = int(rank)
                if f_pts: h_form_pts = f_pts
            elif "away" in t_type:
                if rank: a_rank = int(rank)
                if f_pts: a_form_pts = f_pts

        # 2. Kolla i extra_ev_stat (från /statistics-endpointen)
        if extra_ev_stat:
            standings = extra_ev_stat.get("standings") or extra_ev_stat.get("table") or []
            for row in standings:
                if row.get("isHomeTeam") or row.get("teamType") == "home":
                    h_rank = h_rank or row.get("position") or row.get("rank")
                elif row.get("isAwayTeam") or row.get("teamType") == "away":
                    a_rank = a_rank or row.get("position") or row.get("rank")
                    
            h_f = extra_ev_stat.get("homeForm") or extra_ev_stat.get("formHome")
            a_f = extra_ev_stat.get("awayForm") or extra_ev_stat.get("formAway")
            if h_f and not h_form_pts: h_form_pts = calc_form_pts(h_f)
            if a_f and not a_form_pts: a_form_pts = calc_form_pts(a_f)

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
draw_number = draw.get('drawNumber')

if st.sidebar.button("🔄 Uppdatera all live-statistik"):
    st.cache_data.clear()
    st.rerun()

# Map extra statistics per eventNumber om de finns i /statistics
extra_stats_map = {}
extra_stats_obj = draw.get("_extra_stats", {})
for stat_ev in extra_stats_obj.get("events", extra_stats_obj.get("drawEvents", [])):
    e_num = stat_ev.get("eventNumber")
    if e_num:
        extra_stats_map[e_num] = stat_ev

# --- 3. HELAUTOMATISK STATISTIKMOTOR (ODDS + FORM + TABELL + TT + POISSON-KRYSS) ---
events = draw.get("drawEvents", [])
num_matches = len(events)
match_data = []

for ev in events:
    num = ev.get("eventNumber")
    desc = ev.get("eventDescription", f"Match {num}")
    extra_ev = extra_stats_map.get(num, {})
    
    # 1. Svenska Folket (Streckfördelning)
    sf = ev.get("svenskaFolket") or extra_ev.get("svenskaFolket") or {}
    s1 = float(sf.get("one", 0) or 0)
    sx = float(sf.get("x", 0) or 0)
    s2 = float(sf.get("two", 0) or 0)
    if s1 + sx + s2 == 0:
        s1, sx, s2 = 40.0, 26.0, 34.0
    
    # 2. Tio Tidningars Tips (Experter - kollar både i ev, newspaperAdvice och extra_ev)
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
    
    # 3. Marknadsodds
    odds = ev.get("odds") or extra_ev.get("odds") or {}
    o1 = parse_odd(odds.get("one"))
    ox = parse_odd(odds.get("x"))
    o2 = parse_odd(odds.get("two"))
    
    if o1 > 0 and ox > 0 and o2 > 0:
        inv1, invx, inv2 = (1/o1)**1.05, (1/ox)**1.05, (1/o2)**1.05
        total_inv = inv1 + invx + inv2
        odd_p1 = (inv1 / total_inv) * 100
        odd_px = (invx / total_inv) * 100
        odd_p2 = (inv2 / total_inv) * 100
    else:
        odd_p1, odd_px, odd_p2 = s1, sx, s2

    # 4. Djupstatistik: Tabell & Form
    h_rank, a_rank, h_form, a_form, stat_str = extract_deep_stats(ev, extra_ev)
    
    stat_adj_1, stat_adj_x, stat_adj_2 = 0.0, 0.0, 0.0
    if h_rank and a_rank:
        rank_diff = a_rank - h_rank
        stat_adj_1 += np.clip(rank_diff * 0.22, -3.5, 3.5)
        stat_adj_2 -= np.clip(rank_diff * 0.22, -3.5, 3.5)
        if abs(rank_diff) <= 3:
            stat_adj_x += 1.2

    if h_form > 0 or a_form > 0:
        form_diff = h_form - a_form
        stat_adj_1 += np.clip(form_diff * 0.25, -2.5, 2.5)
        stat_adj_2 -= np.clip(form_diff * 0.25, -2.5, 2.5)

    # 5. Poisson/Fotbolls-korrigering för jämna matcher
    if product != "powerplay" and abs(odd_p1 - odd_p2) <= 10.0:
        stat_adj_x += 1.5

    # 6. Vägsamman allt till en Total AI-Sannolikhet
    if tt_sum > 0:
        tt_p1, tt_px, tt_p2 = (tt1/tt_sum)*100, (ttx/tt_sum)*100, (tt2/tt_sum)*100
        raw_p1 = (odd_p1 * 0.86) + (tt_p1 * 0.14) + stat_adj_1
        raw_px = (odd_px * 0.88) +
