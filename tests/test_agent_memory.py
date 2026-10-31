from datetime import datetime,timezone,timedelta
import pytest
from quantpro.memory import Store
from quantpro.agent import forecast,evaluate_brier
from quantpro.backtest import score_history
from quantpro.research import normalized,FootballResearch,ResearchError


def test_memory_roundtrip(tmp_path):
    db=Store(sqlite_path=tmp_path/'test.db')
    db.put('snapshots','a',{'product':'Stryktipset','draw':4977,'captured_at':'2026-10-31T10:00:00+00:00','source':'official'}, {'matches':[1,2]})
    assert db.list('snapshots')[0]['payload']=={'matches':[1,2]}
    db.put('snapshots','a',{'product':'Stryktipset','draw':4977,'captured_at':'2026-10-31T10:00:00+00:00','source':'official'}, {'matches':[]})
    assert len(db.list('snapshots'))==1
    db.close()


def test_market_baseline():
    result=forecast({'odds':[2,3,4],'streck':[.5,.3,.2]})
    assert sum(result['model'])==pytest.approx(1)
    assert result['market']==result['model']


def test_brier():
    assert evaluate_brier([[1,0,0]],['1'])==0
    assert evaluate_brier([[0,1,0]],['1'])==2


def test_backtest_excludes_leakage():
    t=datetime(2026,10,31,10,tzinfo=timezone.utc)
    payload={'product':'Stryktipset','draw':1,'captured_at':t.isoformat(),'cutoff_at':(t+timedelta(hours=1)).isoformat(),
             'probabilities':[[.5,.25,.25]]}
    forecasts=[{'payload':payload}]
    outcomes=[{'product':'Stryktipset','draw':1,'payload':{'results':['1']}}]
    assert len(score_history(forecasts,outcomes))==1
    payload['captured_at']=(t+timedelta(hours=2)).isoformat()
    assert score_history(forecasts,outcomes)==[]


def test_name_normalization():
    assert normalized('Malmö FF')=='malmoff'


def test_ambiguous_team_rejected():
    class Mock:
        def get(self,path,params): return [{'team':{'name':'Arsenal','id':1}},{'team':{'name':'Arsenal','id':2}}]
    obj=FootballResearch('fake')
    obj.get=Mock().get
    with pytest.raises(ResearchError): obj.find_team('Arsenal')
