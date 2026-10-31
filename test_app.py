import sys
import types
sys.modules.setdefault('streamlit', types.SimpleNamespace(cache_data=lambda **kwargs: lambda f: f))
import numpy as np
import pytest
from App import extract_streck, is_player_duel, normalize, optimize, shin, top_k_rows


def test_shin():
    p, method = shin([2.0, 3.2, 4.0])
    assert np.isclose(sum(p), 1)
    assert np.all(p > 0)


def test_streck_order():
    ev = {'betMetrics': {'values': [
        {'outcome': '2', 'distribution': {'distribution': 20}},
        {'outcome': '1', 'distribution': {'distribution': 50}},
        {'outcome': 'X', 'distribution': {'distribution': 30}}]}}
    assert np.allclose(extract_streck(ev, {}), [0.5, 0.3, 0.2])


def test_h2h_no_false_positive():
    assert not is_player_duel({'betMetrics': {}, 'match': {'type': 'football'}})
    assert is_player_duel({'eventTypeDescription': 'Player duel'})


def test_top_k():
    p = np.tile([0.6, 0.3, 0.1], (8, 1))
    rows = top_k_rows(p, 10)
    probs = [np.prod(p[np.arange(8), row]) for row in rows]
    assert len(set(rows)) == 10
    assert all(a >= b - 1e-14 for a, b in zip(probs, probs[1:]))


def test_budget_and_probability():
    p = np.tile([0.6, 0.3, 0.1], (13, 1))
    s = np.tile([0.7, 0.2, 0.1], (13, 1))
    out = optimize(p, s, 150, 1)
    assert out['cost'] <= 150
    assert len(set(map(tuple, out['rows']))) == 150
    assert 0 <= out['full_hit_chance'] <= 1


def test_missing_streck():
    p = np.tile([0.6, 0.3, 0.1], (8, 1))
    out = optimize(p, None, 10, 1)
    assert out['is_global_optimum']
    assert len(out['rows']) == 10


def test_invalid_budget():
    with pytest.raises(ValueError):
        optimize(np.tile([0.6, 0.3, 0.1], (8, 1)), None, 1, 2)

from App import assess_rows, parse_legacy_txt, strategy_comparison


def test_legacy_file_and_strategies():
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / 'stryktipset_omg_4977 (2).txt'
    old = parse_legacy_txt(path.read_bytes(), 13)
    assert old.shape == (300, 13)
    p = np.tile([0.6, 0.3, 0.1], (13, 1))
    s = np.tile([0.7, 0.2, 0.1], (13, 1))
    evaluation = assess_rows(old, p, s)
    assert 0 < evaluation['chance'] < 1
    strategies = strategy_comparison(p, s, 300, 1)
    assert len(strategies) == 3
    assert all(v['cost'] == 300 for v in strategies.values())
    assert assess_rows(strategies['Högsta träffchans']['rows'], p)['chance'] >= assess_rows(strategies['Balanserad']['rows'], p)['chance'] - 1e-10


def test_legacy_rejects_duplicate():
    with pytest.raises(ValueError):
        parse_legacy_txt('E,1,1,1,1,1,1,1,1\nE,1,1,1,1,1,1,1,1', 8)

from App import backtest_rounds, rows_txt, sign_distribution
import pandas as pd


def test_probability_floor_and_maximum():
    p = np.tile([0.56, 0.30, 0.14], (13, 1))
    s = np.tile([0.78, 0.15, 0.07], (13, 1))
    a = optimize(p, s, 300, 1, 0)
    b = optimize(p, s, 300, 1, 0.30)
    c = optimize(p, s, 300, 1, 0.65)
    assert len(a['rows']) == len(b['rows']) == len(c['rows']) == 300
    assert a['full_hit_chance'] + 1e-12 >= b['full_hit_chance']
    assert a['full_hit_chance'] + 1e-12 >= c['full_hit_chance']
    assert b['full_hit_chance'] >= 0.70 * a['full_hit_chance'] - 1e-12
    assert c['full_hit_chance'] >= 0.35 * a['full_hit_chance'] - 1e-12


def test_txt_roundtrip_and_distribution():
    p = np.tile([0.6, 0.3, 0.1], (8, 1))
    rows = optimize(p, None, 20, 1)['rows']
    assert np.array_equal(parse_legacy_txt(rows_txt(rows, 'powerplay', 17), 8), rows)
    assert np.allclose(sign_distribution(rows).sum(axis=1), 1)


def test_backtest_one_round():
    df = pd.DataFrame([{'draw': 1, 'match': i+1, 'p1': .6, 'px': .3, 'p2': .1,
                        's1': .7, 'sx': .2, 's2': .1, 'result': '1'} for i in range(8)])
    out = backtest_rounds(df, budget=20)
    assert len(out) == 3
    assert (out['Max rätt'] == 8).all()
    assert (out['Antal fullträffar'] == 1).all()


def test_backtest_invalid_results():
    df = pd.DataFrame([{'draw': 1, 'match': i+1, 'p1': .6, 'px': .3, 'p2': .1,
                        's1': .7, 'sx': .2, 's2': .1, 'result': '?'} for i in range(8)])
    with pytest.raises(ValueError):
        backtest_rounds(df)
