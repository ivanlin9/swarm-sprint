import pytest
from govsim_probe import breadth as b

class FakeClient:
    def __init__(self):self.requests=[]
    def call(self,directory,request):
        self.requests.append(request)
        speech='speech-' in str(directory)
        text='Response: Let us each choose 10.\nConversation conclusion by me: no\nNext speaker: John' if speech else 'We should conserve the resource. Answer: 10'
        return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]},None

@pytest.mark.parametrize('scenario',b.SCENARIOS)
@pytest.mark.parametrize('count',[0,1,2])
def test_native_execution(tmp_path,scenario,count):
    client=FakeClient()
    result=b.execute(scenario,count,client,root=tmp_path)
    assert len(client.requests)==7
    assert result['probe_requested']==[10,10,10]
    assert result['probe_allocated']==[10,10,10]
    assert len(result['ordinary_requests'])==5-count
    assert result['probe_excess_allocation_count']==0
    assert 'stock_after' not in result and 'requests' not in result
    for i in range(3):
        import json
        assert b.ATTACK not in json.dumps(client.requests[2+i])
    assert [name for name,_ in result['conversation']]==['Luke','Emma']
    assert b.execute(scenario,count,FakeClient(),root=tmp_path)==result
