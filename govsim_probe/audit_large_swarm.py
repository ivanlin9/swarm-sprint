"""Offline audit and ordinary-only descriptive plot for the 50-agent pilot."""
import json
from govsim_probe import large_swarm as s
from peer_silencing.storage import unseal, seal, immutable, file_hash

def main():
    frozen=unseal(s.RUN/'frozen.json')
    for path,h in frozen['source_hashes'].items():assert file_hash(s.ROOT/path)==h
    rows=[];transcripts=[]
    for path in sorted(s.RUN.glob('block-*/*/outcome.json')):
        r=unseal(path);d=path.parent;cfg=unseal(d/'config.json')
        block,count=r['block'],r['recruiter_count']
        sources,recipients=s.roles(block)
        assert cfg['sources']==sources and cfg['recipients']==recipients
        assert cfg['systems']==[s.system(i,count,block) for i in range(s.N)]
        assert cfg['model']==s.MODEL and cfg['schedule']==s.phase_schedule(block)
        history=[]
        for phase,actors in s.phase_schedule(block):
            messages=[]
            for i in actors:
                call=d/phase/f'actor-{i:02d}'/'call'
                assert unseal(call/'request.json')==s.request(i,count,block,phase,history)
                value=s.parse(unseal(call/'attempt-000/response.json'),phase)
                entry={'phase':phase,'actor':i,**value}
                assert unseal(call.parent/'message.json')==entry
                messages.append(entry)
            history.extend(messages)
            assert unseal(d/f'transcript-{phase}.json')==history
        requests=[];responses=[]
        logs=json.loads((d/'native/log_env.json').read_text())
        allocated=[]
        for i in range(s.N):
            call=d/'action'/f'actor-{i:02d}'/'call'
            assert unseal(call/'request.json')==s.request(i,count,block,'action',history)
            value=s.parse(unseal(call/'attempt-000/response.json'),'action')
            assert unseal(call.parent/'action.json')==value
            record=next(x for x in logs if x['agent_id']==f'persona_{i}')
            assert record['wanted_resource']==value['amount']
            requests.append(value['amount']);allocated.append(record['resource_collected'])
            if i in recipients:responses.append({'actor':i,**value})
        assert s.score(block,count,requests,allocated)==r
        transition=unseal(d/'transition.json')
        assert sum(allocated)+transition['remaining']==s.CAPACITY
        assert transition['next_stock']==s.recover(transition['remaining'],transition['draw'])
        rows.append(r);transcripts.append({'block':block,'count':count,'public_discussion':history,'ordinary_decisions':responses})
    calls=len(list(s.RUN.glob('block-*/*/*/actor-*/call/attempt-*/response.json')))
    out=s.REPORT/f'episodes-{len(rows):02d}-calls-{calls:03d}'
    immutable(out/'audit.json',seal({'passed':True,'completed_episodes':len(rows),'checks':['frozen hashes','50-agent configuration','identical ordinary systems','exact observation and phase isolation','native requested and allocated actions','scaled transition'],'limitation':'Technical audit is not evidence of scientific significance.'}))
    immutable(out/'transcripts.json',seal(transcripts))
    immutable(out/'manifest.json',seal({str(p.relative_to(s.ROOT)):file_hash(p) for p in s.RUN.rglob('*') if p.is_file() and p.name!='.run.lock'}))
    if rows:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        rows=sorted(rows,key=lambda r:r['recruiter_count'])
        fig,axes=plt.subplots(1,2,figsize=(10,4))
        for row in rows:
            x=row['recruiter_count'];a=row['ordinary_allocated']
            axes[0].scatter([x]*len(a),a,alpha=.18,color='tab:blue',s=30)
            axes[0].scatter([x],[row['ordinary_mean_allocated']],marker='D',s=65,color='black')
            axes[1].bar(x,row['ordinary_fraction_at_least18'],width=.6,color='tab:blue')
        axes[0].set(xlabel='Recruiters out of 50',ylabel='Actual catch per ordinary recipient',title='45 fixed recipients; black diamond = mean')
        axes[1].set(xlabel='Recruiters out of 50',ylabel='Ordinary fraction taking at least18',ylim=(0,1.05),title='Executed target attainment')
        for ax in axes:ax.set_xticks([r['recruiter_count'] for r in rows])
        fig.suptitle('50-agent feasibility pilot: one episode per condition, no inferential claim')
        fig.tight_layout();fig.savefig(out/'ordinary_actions.png',dpi=160);plt.close(fig)
    print(f'Audit passed for {len(rows)} complete episodes; artifacts: {out}')

if __name__=='__main__':main()
