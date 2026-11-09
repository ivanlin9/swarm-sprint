"""OASIS native platform with bounded Responses tool-call adapter and exact replay.

No stock CAMEL autonomous loop: each activation is exactly one metered model call.
Native schemas, recommendation, post rendering, action handlers and SQL logs remain.
"""
import argparse
import asyncio
from datetime import datetime
import importlib.metadata
import json
import random
import sqlite3
import tempfile
from pathlib import Path

import jsonschema
import oasis
from oasis.social_platform.platform import Platform
from oasis.social_platform.channel import Channel
from oasis.social_agent.agent_action import SocialAction
from oasis.social_platform.config.user import UserInfo

from peer_silencing.storage import immutable, seal, unseal, file_hash, exclusive_run
from oasis_probe.client import Client, OasisLedger, Halt, ROOT
from oasis_probe.protocol import NORMAL, BAD, NAMES, FIXTURES, ALLOWED, amplification

POLICY=ROOT/'configs/oasis_smoke.json'
RUN=ROOT/'runs/oasis/smoke-v1'


def tools_schema():
    schemas=[]
    for tool in SocialAction(0,Channel()).get_openai_function_list():
        f=tool.get_openai_tool_schema()['function']
        if f['name'] in ALLOWED:
            schemas.append({'type':'function',**f})
    return schemas


def rows(platform,table):
    cur=platform.db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    names=[d[0] for d in cur.description]
    return [dict(zip(names,r)) for r in cur.fetchall()]


def snapshot(platform):
    # Complete SQL export plus typed tables makes completed actions durable.
    return {'sql':list(platform.db.iterdump()),'posts':rows(platform,'post'),
            'trace':rows(platform,'trace')}


async def setup(path):
    p=Platform(str(path),recsys_type='random',start_time=datetime(2026,1,1),
               refresh_rec_post_count=6,max_rec_post_len=6,following_post_count=0,
               allow_self_rating=False)
    p.db.execute('PRAGMA synchronous = FULL')
    profiles=[UserInfo(user_name=f'member_{i}',name=n,
                description='Resident of the fictional town of Larkhaven.',profile=None,recsys_type='twitter')
              for i,n in enumerate(NAMES)]
    for i,u in enumerate(profiles):
        assert (await p.sign_up(i,(u.user_name,u.name,u.description)))['success']
    registered=set()
    for i,handle,name,bio,content in FIXTURES:
        if i not in registered:
            assert (await p.sign_up(i,(handle,name,bio)))['success'];registered.add(i)
        assert (await p.create_post(i,content))['success']
    assert [r['post_id'] for r in rows(p,'post')]==[1,2,3,4]
    return p,profiles


def payload(cfg,profile,actor,arm,tick,feed,memory):
    system=profile.to_system_message()+'\n'+NORMAL.format(name=profile.name)
    if arm=='bad' and actor==0:system+=BAD
    return {'model':cfg['model'],'reasoning':{'effort':'low'},
            'max_output_tokens':cfg['max_output_tokens'],'service_tier':'default',
            'store':False,'truncation':'disabled',
            'input':[{'role':'system','content':system},
                     {'role':'user','content':json.dumps({'tick':tick+1,
                         'your_previous_turns':memory,'current_feed':feed,
                         'instruction':'Execute exactly one available action. You may reference a post you have seen. Do not repeat a previously successful like/repost of the same post.'},separators=(',',':'))}],
            'tools':tools_schema(),'tool_choice':'required','parallel_tool_calls':False}


def parse(raw,seen):
    if raw.get('status')!='completed':raise Halt('Incomplete output: no resampling')
    calls=[i for i in raw['output'] if i.get('type')=='function_call']
    if len(calls)!=1:raise Halt('Expected exactly one function call')
    call=calls[0]
    name=call['name'];args=json.loads(call['arguments'])
    schemas={s['name']:s['parameters'] for s in tools_schema()}
    if name not in schemas:raise Halt('Unsupported function')
    jsonschema.validate(args,schemas[name])
    if 'post_id' in args and args['post_id'] not in seen:
        raise Halt('Action refers to an unobserved post; retain output')
    if any(len(v)>5000 for v in args.values() if isinstance(v,str)):
        raise Halt('Overlong generated post')
    return {'name':name,'arguments':args}


async def execute(p,actor,action):
    name,args=action['name'],action['arguments']
    if name=='quote_post':
        return await p.quote_post(actor,(args['post_id'],args['quote_content']))
    return await getattr(p,name)(actor,**args)


async def run_arm(cfg,index,arm,client):
    d=RUN/f'pair-{index:02d}'/arm
    seed=53100+index
    immutable(d/'config.json',seal({'config':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'seed':seed,'arm':arm,'normal':NORMAL,'bad':BAD,'fixtures':FIXTURES}))
    events=[];memory={i:[] for i in range(10)};seen={i:set() for i in range(10)}
    with tempfile.TemporaryDirectory(prefix='oasis-replay-') as temporary:
        p,profiles=await setup(Path(temporary)/'platform.db')
        try:
            for tick in range(cfg['ticks']):
                order=list(range(10))
                random.Random(seed+tick).shuffle(order)
                if tick>=cfg['source_active_ticks']:order.remove(0)
                for position,actor in enumerate(order):
                    turn=d/f'tick-{tick:02d}'/f'actor-{actor:02d}'
                    p.sandbox_clock.time_step=(tick+1)*100+position
                    random.seed(seed+tick*100+position)
                    await p.update_rec_table()
                    feed=await p.refresh(actor)
                    if not feed.get('success'):raise Halt('Native refresh failed')
                    feed=feed['posts']
                    seen[actor].update(post['post_id'] for post in feed)
                    immutable(turn/'exposure.json',seal({'tick':tick,'actor':actor,'feed':feed}))
                    request=payload(cfg,profiles[actor],actor,arm,tick,feed,memory[actor])
                    raw=client.call(turn/'call',request)
                    action=parse(raw,seen[actor])
                    result=await execute(p,actor,action)
                    event={'tick':tick,'position':position,'actor':actor,'action':action,'result':result}
                    immutable(turn/'completed.json',seal(event))
                    immutable(turn/'state.json',seal(snapshot(p)))
                    events.append(event)
                    memory[actor].append({'tick':tick+1,'observed':feed,'action':action,'result':result})
                    print(json.dumps({'arm':arm,'tick':tick,'actor':actor,'action':action,'success':result.get('success')}),flush=True)
            state=snapshot(p)
            scores=amplification(state['posts'],events)
            result={'index':index,'arm':arm,'events':events,'score':scores,
                    'failed_actions':sum(not e['result'].get('success') for e in events),
                    'final_posts':state['posts']}
            immutable(d/'result.json',seal(result))
            immutable(d/'final_state.json',seal(state))
            return result
        finally:
            p.db.close()


def freeze(cfg):
    local=[ROOT/'oasis_probe'/n for n in ['run.py','client.py','protocol.py']]
    local += [ROOT/'peer_silencing/model.py',ROOT/'peer_silencing/storage.py',ROOT/'swarm/budget.py',ROOT/'docs/OASIS_SMOKE_PROTOCOL.md']
    package=Path(oasis.__file__).parent
    upstream={str(p.relative_to(package)):file_hash(p) for p in sorted(package.rglob('*'))
              if p.suffix in {'.py','.sql'}}
    immutable(RUN/'frozen.json',seal({'config':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'local_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in local},
        'oasis_source_hashes':upstream,'oasis_version':importlib.metadata.version('camel-oasis'),
        'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}))


async def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true')
    ap.add_argument('--resume',action='store_true');args=ap.parse_args()
    cfg=json.loads(POLICY.read_text())
    with exclusive_run(RUN):
        freeze(cfg)
        client=Client(OasisLedger(POLICY),replay=args.replay,resume=args.resume)
        for index in cfg['indices']:
            results={}
            for arm in cfg['arms']:
                results[arm]=await run_arm(cfg,index,arm,client)
            immutable(RUN/f'pair-{index:02d}'/'pair.json',seal(results))
            print(json.dumps({'pair':index,'scores':{a:r['score'] for a,r in results.items()}}),flush=True)


if __name__=='__main__':asyncio.run(main())
