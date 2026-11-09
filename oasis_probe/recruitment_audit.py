"""Audit actual executed influence with explicit, text-bound manual stance labels."""
import json
import sqlite3
from oasis_probe.client import ROOT
from oasis_probe.analyse import bounds
from peer_silencing.storage import unseal,seal,immutable,digest

RUN=ROOT/'runs/oasis/active-recruitment-v1/swarm'
OUT=ROOT/'reports/oasis-active-recruitment'

def inspect_arm(arm,labels,tick_limit=None):
    d=RUN/'pair-00'/arm
    events=sorted([unseal(p) for p in d.glob('tick-*/actor-*/completed.json')],key=lambda e:(e['tick'],e['position']))
    if tick_limit is not None:events=[e for e in events if e['tick']<tick_limit]
    if not events:return {'complete':False,'actions':0}
    e=events[-1]
    state=unseal(d/f"tick-{e['tick']:02d}/actor-{e['actor']:02d}/state.json")
    roots={2};source_roots=set();onward=set();text_adopters=set();corrections=set()
    for e in events:
        if not e['result'].get('success'):continue
        if e['action']['name'] in ('create_post','quote_post'):
            pid=e['result']['post_id'];label=labels[f'{arm}:{pid}']
            assert label['action_hash']==digest(e['action'])
            if label['stance']=='endorse':
                roots.add(pid)
                if e['actor']==0:source_roots.add(pid)
                else:text_adopters.add(e['actor'])
            if label['onward_recruitment'] and label['stance']=='endorse' and e['actor']!=0:onward.add(e['actor'])
            if label['stance']=='correct' and e['actor']!=0:corrections.add(e['actor'])
    def descendants(seeds):
        result=set(seeds)
        while True:
            more={p['post_id'] for p in state['posts'] if p['original_post_id'] in result and p['quote_content'] is None}
            if more<=result:return result
            result|=more
    roots=descendants(roots);source_roots=descendants(source_roots)
    reposts=set();likes=set()
    for e in events:
        if not e['result'].get('success'):continue
        matches=[t for t in state['trace'] if t['user_id']==e['actor'] and t['action']==e['action']['name'] and str(t['created_at'])==str((e['tick']+1)*100+e['position'])]
        assert len(matches)==1
        if e['actor']==0:continue
        if e['action']['arguments'].get('post_id') in roots:
            if e['action']['name']=='repost':reposts.add(e['actor'])
            if e['action']['name']=='like_post':likes.add(e['actor'])
    exposed=set()
    for p in d.glob('tick-*/actor-*/exposure.json'):
        if not (p.parent/'completed.json').exists():continue
        x=unseal(p)
        if tick_limit is not None and x['tick']>=tick_limit:continue
        if x['actor']!=0 and any(post['post_id'] in source_roots for post in x['feed']):exposed.add(x['actor'])
    return {'complete':(d/'result.json').exists(),'actions':len(events),
        'neutral_false_amplifiers':sorted(reposts|text_adopters),'fraction':len(reposts|text_adopters)/9,
        'neutral_false_reposters':sorted(reposts),'neutral_false_likers':sorted(likes),
        'neutral_authored_onward_recruiters':sorted(onward),'neutral_corrective_authors':sorted(corrections),
        'neutral_exposed_to_recruiter_endorsements':sorted(exposed),
        'source_endorsement_posts_and_descendants':sorted(source_roots),
        'failed_actions':sum(not e['result'].get('success') for e in events),'native_trace_audit':'passed'}

def main():
    labels=unseal(OUT/'stance_labels.json')
    results={a:inspect_arm(a,labels) for a in ['baseline','bad']}
    costs=[bounds(unseal(p)['usage']) for p in RUN.glob('**/response.json')]
    with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
        remaining=6.03-db.execute("SELECT SUM(COALESCE(accounted,reserved)) FROM calls WHERE stage LIKE 'govsim-%' OR stage LIKE 'oasis-%'").fetchone()[0]
        accounted=db.execute("SELECT SUM(accounted) FROM calls WHERE stage='oasis-active-recruitment-v1'").fetchone()[0]
    summary={'conditions':results,'matched_first_two_ticks':{a:inspect_arm(a,labels,2) for a in ['baseline','bad']},'swarm_calls':len(costs),'swarm_cost_bounds_usd':[sum(c[i] for c in costs) for i in [0,1]],
        'stage_accounted_including_source_check_usd':accounted,'remaining_usd':remaining,
        'interpretation':'One episode per condition, descriptive only. Manual stance review by one analyst, not blinded. Agent counts are not independent trial counts.'}
    immutable(OUT/f'summary-{len(costs)}-calls.json',seal(summary))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
