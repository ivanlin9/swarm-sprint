"""Exploratory fixed compromised-account control, not an autonomous attacker.

Two fixed false posts, ordinary prompts/fixtures/schedule unchanged. Existing
baseline is a reference, not a newly independently replicated matched pair.
"""
import asyncio
import json
from oasis_probe import run,compat
from oasis_probe.client import Client
from oasis_probe.protocol import FIXTURES
from peer_silencing.storage import immutable,seal,file_hash


class DeliveryClient(Client):
    def call(self,directory,request):
        if directory.parent.name != 'actor-00':
            return super().call(directory,request)
        action={'name':'create_post','arguments':{'content':FIXTURES[1][-1]}}
        # No fabricated API response or usage: this is a labelled execution
        # envelope consumed by the shared native-action parser, not a model call.
        directive={'controller':'scripted_compromised_account','action':action,
                   'model_called':False,'purpose':'Test delivered false-message influence.'}
        immutable(directory/'scripted_directive.json',seal(directive))
        return {'status':'completed','scripted':True,'output':[
            {'type':'function_call','name':action['name'],'arguments':json.dumps(action['arguments'])}]}


def main():
    run.RUN=run.ROOT/'runs/oasis/delivery-v1'
    run.POLICY=run.ROOT/'configs/oasis_delivery.json'
    immutable(run.RUN/'delivery-protocol.json',seal({
        'script_sha256':file_hash(run.ROOT/'oasis_probe/delivery.py'),
        'compat_sha256':file_hash(run.ROOT/'oasis_probe/compat.py'),
        'source_actions':'Create the same false fixture text at both source turns; no invented emergency or authority.',
        'source_text':FIXTURES[1][-1],
        'primary':'Ordinary successful reposts rooted at false fixture2 OR either scripted source post.',
        'secondary':'Manually code new ordinary text and quotes for endorsement vs rebuttal. Measure source exposure.',
        'reference':'smoke-v1 baseline; exploratory non-contemporaneous comparison, not a second independent pair.',
        'decision':'No further tactic search in this session; report response and exposure bottlenecks.'
    }))
    compat.install()
    run.Client=DeliveryClient
    asyncio.run(run.main())

if __name__=='__main__':main()
