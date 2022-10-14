from dataflow import flow
from bytewax.execution import run_main
from bytewax.outputs import TestingOutputConfig


def test_dataflow():
    out = []
    flow.capture(TestingOutputConfig(out))
    run_main(flow)
    data = [('commons.wikimedia.org', 1),
('ca.wikipedia.org', 1),
('species.wikimedia.org', 1),
('en.wikipedia.org', 2),
('ar.wikipedia.org', 1),
('fr.wikipedia.org', 1),
('id.wikipedia.org', 9),
('www.wikidata.org', 15),
('ro.wikipedia.org', 1),]
    assert sorted(out) == sorted(data)
