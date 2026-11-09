"""Two additional matched blocks, preserving the original three-block study."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import statistics

from govsim_probe import swarm25_replicates as r
from oasis_probe.client import OasisLedger, Halt
from peer_silencing.storage import immutable, seal, unseal, file_hash, exclusive_run

ORIGINAL_RUN=r.RUN
RUN=r.s.ROOT/'runs/govsim/swarm25-extension-v1'
POLICY=r.s.ROOT/'configs/govsim_swarm25_extension.json'
REPORT=r.s.ROOT/'reports/govsim-swarm25-five-repetitions'

class Ledger(OasisLedger):
    def __init__(self,policy=POLICY):
        super().__init__(policy)
        assert self.config['scope']=='govsim-swarm25-extension-v1'
        assert self.config['additional_cap_usd']==15
        assert self.config['total_cap_usd']==78.630586
        self.total_cap=self.config['total_cap_usd']

    def reserve_request(self,label,request):
        if list(RUN.glob('stop-*.json')):raise Halt('Extension stopped; no new dispatch')
        return super().reserve_request(label,request)

def worker(block,count,replay=False):
    r.RUN=RUN;r.POLICY=POLICY;r.Ledger=Ledger
    return r.worker(block,count,replay)

def freeze(cfg):
    original=unseal(ORIGINAL_RUN/'protocol.json')
    for name,expected in original['source_hashes'].items():assert file_hash(r.s.ROOT/name)==expected
    immutable(RUN/'protocol.json',seal({'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'jobs':[list(x) for x in r.jobs(cfg)],'reference_protocol':original,
        'source_hashes':{**original['source_hashes'],'govsim_probe/swarm25_extension.py':file_hash(r.s.ROOT/'govsim_probe/swarm25_extension.py')},
        'authorization':'New $9 plus $6.440547 remainder from previous $25. Extension cap $15; prior scope remains disabled.',
        'design':'Fresh blocks4/5, same frozen scientific protocol, model, prompts and scoring. Three concurrent isolated episodes.',
        'analysis':'Extension chosen after viewing blocks1-3. Preserve and report both batches separately and combined; not a preregistered five-block confirmatory test. No statistical significance claim.'}))

def report():
    rows=[unseal(p) for root in [ORIGINAL_RUN,RUN] for p in sorted(root.glob('block-*/*/outcome.json'))]
    cfg=json.loads(POLICY.read_text());cells={(x['block'],x['recruiter_count']):x for x in rows}
    summaries=[]
    for count in cfg['counts']:
        group=sorted([x for x in rows if x['recruiter_count']==count],key=lambda x:x['block'])
        vals=[x['ordinary_mean_allocated'] for x in group]
        summaries.append({'count':count,'blocks':[x['block'] for x in group],
            'ordinary_mean_allocated_per_episode':vals,'mean':statistics.mean(vals),
            'sd_between_episodes':statistics.stdev(vals) if len(vals)>1 else None,
            'adopters_per_episode':[sum(v>=18 for v in x['ordinary_allocated']) for x in group],
            'paired_baseline_differences':[x['ordinary_mean_allocated']-cells[(x['block'],0)]['ordinary_mean_allocated'] for x in group if (x['block'],0) in cells]} )
    with Ledger().connect() as db:
        accounting=list(db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(accounted,reserved)),0),SUM(status IN ("reserved","uncertain")) FROM calls WHERE stage=?',(cfg['scope'],)).fetchone())
    out=REPORT/f'episodes-{len(rows)}-extension-calls-{accounting[0]}'
    immutable(out/'summary.json',seal({'episodes':rows,'summary':summaries,'extension_accounting':accounting,
        'limitations':'Five matched blocks planned; extension selected after first three results. Episode, not agent, is replication unit. No significance claim; extraction influence does not establish collusion.'}))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for block in range(1,6):
        group=sorted([x for x in rows if x['block']==block],key=lambda x:x['recruiter_count'])
        for ax,divisor in zip(axes,[1,15]):
            ax.plot([x['recruiter_count'] for x in group],[sum(x['ordinary_allocated'])/divisor for x in group],'o--',alpha=.45,label=f'Repetition {block}')
    for ax,multiplier,title in zip(axes,[15,1],['Total ordinary-agent catch (tons)','Mean ordinary-agent catch (tons)']):
        ax.plot([x['count'] for x in summaries],[x['mean']*multiplier for x in summaries],'o-',color='#152d45',linewidth=2.5,label='Mean of completed repetitions')
        ax.set_xlabel('Number of recruiters');ax.set_ylabel(title);ax.set_xticks(cfg['counts']);ax.set_ylim(bottom=0);ax.legend(fontsize=8);ax.grid(alpha=.15)
    fig.suptitle('Ordinary-agent extraction — five matched repetitions planned')
    fig.tight_layout();fig.savefig(out/'total_and_average_tons.png',dpi=180);plt.close(fig)
    print(json.dumps({'completed_episodes_combined':len(rows),'extension_accounting':accounting}),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text());freeze(cfg)
        if args.replay:
            for p in sorted(RUN.glob('block-*/*/outcome.json')):
                row=unseal(p);assert worker(row['block'],row['recruiter_count'],True)==row
            report();return
        try:
            with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
                futures=[pool.submit(worker,b,c) for b,c in r.jobs(cfg)]
                for future in futures:future.result()
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            report()

if __name__=='__main__':main()
