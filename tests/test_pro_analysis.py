import pytest
from quantpro.auto_data import parse_draw, FeedError
from quantpro.pro_analysis import probabilities, top_rows, summarize, export_txt, score_rows

def matches(n=13):
    return [{'Nr':i+1,'Hemma':f'A{i}', 'Borta':f'B{i}', 'odds':[2.0,3.5,4.0], 'streck':[.5,.25,.25]} for i in range(n)]

def test_odds():
    p=probabilities([2,3.5,4]); assert sum(p)==pytest.approx(1); assert p[0]>p[1]>p[2]

def test_top_rows():
    rows=top_rows(matches(), 300); assert len(rows)==300 and len(set(rows))==300
    assert rows[0]=='1'*13
    assert summarize(rows,matches())['chance_13_or_8']>0

def test_export():
    data=export_txt(['1'*13, 'X'*13], 'Stryktipset', 4977)
    assert data.startswith(b'Stryktipset,Omg=4977\r\nE,1,')

def test_score():
    r=score_rows(['1'*13, 'X'*13], ['1']*11+['?']*2)
    assert r['max_possible']==13 and r['distribution'][11]==1

def test_parse_realistic():
    data={'draw':{'events':[{'eventNumber':i+1, 'participants':[{'type':'home','name':f'H{i}'},{'type':'away','name':f'A{i}'}],
                 'odds':{'one':2.0,'x':3.5,'two':4.0}, 'svenskaFolket':{'one':50,'x':25,'two':25}} for i in range(13)]}}
    rows=parse_draw(data,'Stryktipset'); assert len(rows)==13 and rows[0]['odds']==[2,3.5,4]

def test_no_partial():
    with pytest.raises(FeedError): parse_draw({'events':[]},'Stryktipset')

def test_invalid_odds():
    with pytest.raises(ValueError): probabilities([1,2,3])
