import pytest
from quantpro.engine import normalize, probabilities_from_odds, analyze_match, score_rows

def test_normalization():
    assert sum(normalize([2,3,5])) == pytest.approx(1)

def test_market():
    assert sum(probabilities_from_odds([2,3,4])) == pytest.approx(1)

def test_values():
    result = analyze_match([2,3,4], [50,25,25])
    assert len(result) == 3
    assert result[0]['Tecken'] == '1'

def test_partial_scores():
    x = score_rows([list('11111111'),list('X1111111')], ['1']+[None]*7)
    assert x[0] == {'rätt_nu':1,'max_rätt':8}
    assert x[1] == {'rätt_nu':0,'max_rätt':7}

def test_invalid():
    with pytest.raises(ValueError): probabilities_from_odds([1,2,3])
    with pytest.raises(ValueError): score_rows([['1']*8], ['?']*8)
