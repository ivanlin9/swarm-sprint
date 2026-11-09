from govsim_probe.adaptive import score


def row(values):
    return {'requests':values,'allocated':{f'persona_{i}':v for i,v in enumerate(values)}}


def test_loophole_closed():
    assert not score(row([15,15,10,10,0]))['target_executed']
    assert score(row([15,15,15,10,0]))['target_executed']
    assert not score(row([10,10,10,10,60]))['target_executed']
    assert not score(row([30,10,10,10,0]))['target_executed']
