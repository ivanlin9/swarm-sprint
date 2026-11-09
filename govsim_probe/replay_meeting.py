"""Network-disabled replay, normalizing tuple/list serialization at artifact writes.

The frozen paid runner remains unchanged. JSON stores conversation tuples as
lists; normalize before comparing existing artifacts to avoid a false mismatch.
"""
import json
from govsim_probe import meeting as m
from peer_silencing.storage import immutable


def json_immutable(path, value):
    immutable(path, json.loads(json.dumps(value)))


class NoNetwork:
    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        raise RuntimeError('Network forbidden during saved-response replay')


def main():
    original_client = m.voting.Client
    m.immutable = json_immutable
    m.voting.Client = lambda ledger: original_client(ledger, transport=NoNetwork())
    m.main()


if __name__ == '__main__':
    main()
