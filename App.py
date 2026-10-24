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
        for ch in
