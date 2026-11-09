import pytest
from govsim_probe import resume_recruitment_dose as r
from peer_silencing.storage import immutable,seal,digest
from oasis_probe.client import Halt

def fixture(tmp_path,monkeypatch):
    req={'input':[{'role':'user','content':'unchanged'}]}
    monkeypatch.setattr(r,'FAILED',tmp_path)
    monkeypatch.setattr(r,'REQUEST_HASH',digest(req))
    immutable(tmp_path/'request.json',seal(req))
    immutable(tmp_path/'attempt-000/intent.json',seal({'call_id':r.CALL_ID,'request_hash':digest(req)}))
    immutable(tmp_path/'attempt-000/error.json',seal({'type':'APIConnectionError','status':None,'rejected':False}))
    return req

def test_exact_replacement_only(tmp_path,monkeypatch):
    req=fixture(tmp_path,monkeypatch)
    assert r.replacement_path(tmp_path,req)==tmp_path/'authorized-replacement-001'
    assert r.replacement_path(tmp_path/'other',req)==tmp_path/'other'
    with pytest.raises(AssertionError):r.replacement_path(tmp_path,{'input':'different'})

def test_original_response_conflict(tmp_path,monkeypatch):
    req=fixture(tmp_path,monkeypatch)
    immutable(tmp_path/'attempt-000/response.json',seal({'id':'late'}))
    with pytest.raises(Halt,match='reconcile'):r.replacement_path(tmp_path,req)

def test_routes_once_and_reuses_cache(tmp_path,monkeypatch):
    req=fixture(tmp_path,monkeypatch);seen=[]
    def fake_call(self,directory,request):
        seen.append(directory)
        return {'id':'cached'}
    monkeypatch.setattr(r.Client,'call',fake_call)
    client=r.RecoveryClient(None)
    client.call(tmp_path,req);client.call(tmp_path,req)
    assert seen==[tmp_path/'authorized-replacement-001']*2
