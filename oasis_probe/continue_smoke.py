"""Resume original smoke with disclosed quote-report compatibility repair."""
import asyncio
from oasis_probe import run, compat
from peer_silencing.storage import immutable, seal, file_hash

def main():
    immutable(run.RUN/'compatibility-repair.json', seal({
        'reason': 'Native quote renderer does not initialise num_reports.',
        'patch_sha256': file_hash(run.ROOT/'oasis_probe/compat.py'),
        'runner_sha256': file_hash(run.ROOT/'oasis_probe/continue_smoke.py'),
        'first_missing_action': 'pair-00/bad/tick-02/actor-07',
        'previous_calls':52,
        'policy':'Replay and byte-compare every previously saved exposure/action/state before new calls; no stimulus or decision changes.'
    }))
    compat.install()
    asyncio.run(run.main())

if __name__=='__main__':main()
