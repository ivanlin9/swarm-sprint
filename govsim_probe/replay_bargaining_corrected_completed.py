"""Replay completed corrected episodes only; no dispatch of unfinished cells."""
from govsim_probe import bargaining_corrected as b
from peer_silencing.storage import unseal,file_hash,exclusive_run
from oasis_probe.client import Client,OasisLedger
from govsim_probe.discussion import NativeClient

if __name__=='__main__':
    with exclusive_run(b.RUN):
        for name,h in unseal(b.RUN/'frozen.json')['source_hashes'].items():assert file_hash(b.ROOT/name)==h
        client=NativeClient(Client(OasisLedger(b.POLICY),replay=True))
        paths=sorted(b.RUN.glob('block-*/*/outcome.json'))
        for p in paths:
            expected=unseal(p)
            assert b.execute(expected['index'],expected['condition'],client)==expected
        print(f'Offline replay passed for {len(paths)} completed episodes; unfinished cells not dispatched.')
