"""Single-request Responses transport with durable shared budget and replay."""
import json
import uuid
from pathlib import Path
from dotenv import dotenv_values
from openai import OpenAI, APIStatusError
from peer_silencing.model import SharedLedger
from peer_silencing.storage import immutable, seal, unseal, digest
from swarm.budget import BudgetExceeded

ROOT = Path(__file__).resolve().parents[1]


class Halt(RuntimeError):
    pass


class OasisLedger(SharedLedger):
    def __init__(self, policy):
        super().__init__(ROOT/'runs/spending.sqlite3',testing_cap=12,total_cap=45)
        self.policy_path = policy
        self.config = json.loads(policy.read_text())

    def reserve_request(self, label, request):
        cfg = json.loads(self.policy_path.read_text())
        if not cfg['paid_enabled'] or cfg != self.config:
            raise Halt('Paid execution disabled or configuration changed')
        amount = self.reserve_amount(request,request['max_output_tokens'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            costs = dict(db.execute('SELECT stage,SUM(COALESCE(accounted,reserved)) FROM calls GROUP BY stage'))
            subtotal = costs.get(cfg['scope'],0)
            shared = sum(v for k,v in costs.items() if k.startswith(('govsim-','oasis-')))
            if (subtotal+amount>cfg['additional_cap_usd'] or
                shared+amount>cfg['shared_govsim_oasis_cap_usd'] or
                sum(costs.values())+amount>self.total_cap):
                raise BudgetExceeded('OASIS/shared allowance cannot reserve next request')
            cid=uuid.uuid4().hex
            db.execute('INSERT INTO calls(id,stage,label,status,reserved) VALUES (?,?,?,?,?)',
                       (cid,cfg['scope'],label,'reserved',amount))
        return cid

    def rejected(self,cid):
        with self.connect() as db:
            db.execute("UPDATE calls SET status='rejected',accounted=0,estimate=0 WHERE id=? AND status='reserved'",(cid,))


class Client:
    def __init__(self,ledger,replay=False,resume=False,transport=None):
        self.ledger,self.replay,self.resume = ledger,replay,resume
        self.api=transport
        self.stopped=False

    def call(self,directory,request):
        immutable(directory/'request.json',seal(request))
        for attempt in range(10):
            d=directory/f'attempt-{attempt:03d}'
            if (d/'intent.json').exists():
                intent=unseal(d/'intent.json')
                if intent['request_hash']!=digest(request):raise Halt('Request changed on resume')
                cid=intent['call_id']
                if (d/'response.json').exists():
                    raw=unseal(d/'response.json')
                    self.ledger.settle(cid,raw.get('usage') or {},raw['id'])
                    return raw
                if (d/'error.json').exists():
                    err=unseal(d/'error.json')
                    if err['rejected']:
                        self.ledger.rejected(cid)
                        if self.resume and not self.replay:continue
                    raise Halt('Prior API failure: explicit resume required after resolving cause')
                raise Halt('Uncertain dispatch; do not resend without audit')
            if self.replay:raise Halt('Replay would require a new model request')
            if self.stopped:raise Halt('Dispatch stopped after failure')
            cid=self.ledger.reserve_request(str(directory.relative_to(ROOT)),request)
            immutable(d/'intent.json',seal({'call_id':cid,'request_hash':digest(request)}))
            try:
                if self.api is None:
                    cfg=dotenv_values(ROOT/'.env',interpolate=False)
                    self.api=OpenAI(api_key=cfg.get('OPENAI_API_KEY'),
                        organization=cfg.get('OPENAI_ORG_ID') or None,
                        project=cfg.get('OPENAI_PROJECT_ID') or None,
                        base_url='https://api.openai.com/v1',max_retries=0,timeout=90)
                raw=self.api.responses.create(**request).model_dump(mode='json')
                immutable(d/'response.json',seal(raw))
                self.ledger.settle(cid,raw.get('usage') or {},raw['id'])
                return raw
            except Exception as exc:
                self.stopped=True
                status=exc.status_code if isinstance(exc,APIStatusError) else None
                rejected=status in (400,401,403,404,422,429)
                immutable(d/'error.json',seal({'type':type(exc).__name__,'status':status,'rejected':rejected}))
                if rejected:self.ledger.rejected(cid)
                else:self.ledger.uncertain(cid)
                raise Halt(f'API/accounting stop: {type(exc).__name__}, status {status}; no retry') from None
        raise Halt('Attempt limit')
