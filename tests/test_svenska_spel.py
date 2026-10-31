import pytest
from quantpro.svenska_spel import parse_draw, FeedError

def test_13_matches():
    events = [{'participants': [{'type': 'home', 'name': f'H{i}'}, {'type': 'away', 'name': f'A{i}'}]} for i in range(13)]
    matches = parse_draw({'events': events}, 'stryktipset')
    assert len(matches) == 13 and matches[0]['Hemma'] == 'H0'

def test_incomplete_coupon_rejected():
    with pytest.raises(FeedError):
        parse_draw({'events': []}, 'stryktipset')

def test_eight_matches():
    events = [{'participants': [{'type': 'home', 'name': f'H{i}'}, {'type': 'away', 'name': f'A{i}'}]} for i in range(8)]
    assert len(parse_draw({'events': events}, 'topptipset')) == 8
