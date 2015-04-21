from __future__ import unicode_literals
from nose.tools import (assert_equal, raises, assert_raises,
                        assert_in, assert_is_instance)
from linkpred.evaluation.listeners import *

import io
import linkpred
import networkx as nx
import os
import smokesignal
import sys
import tempfile


def test_imports():
    linkpred.LinkPred
    linkpred.read_network
    linkpred.network
    linkpred.exceptions
    linkpred.evaluation
    linkpred.predictors


def test_for_comparison():
    from linkpred.linkpred import for_comparison
    from linkpred.evaluation import Pair

    G = nx.path_graph(10)
    expected = set(Pair(x) for x in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5),
                                     (5, 6), (6, 7), (7, 8), (8, 9)])
    assert_equal(for_comparison(G), expected)

    to_delete = [Pair(2, 3), Pair(8, 9)]
    expected = expected.difference(to_delete)
    assert_equal(for_comparison(G, exclude=to_delete), expected)


# XXX This may fail because of hash randomization
def test_pretty_print():
    from linkpred.linkpred import pretty_print

    name = "foo"
    assert_equal(pretty_print(name), "foo")
    params = {"bar": 0.1, "baz": 5}

    # 2 possibilities because of hash randomization
    assert_in(pretty_print(name, params), ["foo (baz = 5, bar = 0.1)",
                                           "foo (bar = 0.1, baz = 5)"])


def test_read_unknown_network_type():
    fd, fname = tempfile.mkstemp(suffix=".foo")
    with assert_raises(linkpred.exceptions.LinkPredError):
        linkpred.read_network(fname)
    os.close(fd)
    os.unlink(fname)


def test_read_network():
    fd, fname = tempfile.mkstemp(suffix=".net")
    with open(fname, "w") as fh:
        fh.write("""*vertices 2
1 "A"
2 "B"
*arcs 2
1 2
2 1""")
    expected = nx.DiGraph()
    expected.add_edges_from([("A", "B"), ("B", "A")])

    G = linkpred.read_network(fname)
    assert_equal(set(G.edges()), set(expected.edges()))

    with open(fname) as fh:
        G = linkpred.read_network(fname)
        assert_equal(set(G.edges()), set(expected.edges()))

    os.close(fd)
    os.unlink(fname)


def test_read_pajek():
    from linkpred.linkpred import _read_pajek

    fd, fname = tempfile.mkstemp(suffix=".net")
    with open(fname, "w") as fh:
        fh.write("""*vertices 2
1 "A"
2 "B"
*arcs 2
1 2
1 2""")
    expected = nx.DiGraph()
    expected.add_edges_from([("A", "B")])

    G = _read_pajek(fname)
    assert_is_instance(G, nx.DiGraph)
    assert_equal(sorted(G.edges()), sorted(expected.edges()))

    with open(fname, "w") as fh:
        fh.write("""*vertices 2
1 "A"
2 "B"
*edges 2
1 2
1 2""")
    expected = nx.Graph()
    expected.add_edges_from([("A", "B")])

    G = _read_pajek(fname)
    assert_is_instance(G, nx.Graph)
    assert_equal(sorted(G.edges()), sorted(expected.edges()))


@raises(linkpred.exceptions.LinkPredError)
def test_LinkPred_without_predictors():
    linkpred.LinkPred()


class TestLinkpred:
    def teardown(self):
        smokesignal.clear_all()

    def config_file(self, training=False, test=False, **kwargs):
        config = {'predictors': ['Random'], 'label': 'testing'}

        # add training and test files, if needed

        # Make sure we get bytes
        b = lambda s: str(s) if sys.version_info[0] == 2 else \
            s.encode('latin-1')
        for var, name, fname, data in ((training, 'training', 'foo.net',
                                        b('*Vertices 3\n1 A\n2 B\n3 C\n*Edges '
                                          '1\n1 2 1\n')),
                                       (test, 'test', 'bar.net',
                                        b('*Vertices 3\n1 A\n2 B\n3 C\n*Edges '
                                          '1\n3 2 1\n'))):
            if var:
                fh = io.BytesIO()
                fh.name = fname
                fh.write(data)
                fh.seek(0)
                config['{}-file'.format(name)] = fh

        config.update(kwargs)
        return config

    def test_init(self):
        lp = linkpred.LinkPred(self.config_file())
        assert_equal(lp.config['label'], 'testing')
        assert lp.training is None

        lp = linkpred.LinkPred(self.config_file(training=True))
        assert_is_instance(lp.training, nx.Graph)
        assert_equal(len(lp.training.nodes()), 3)
        assert_equal(len(lp.training.edges()), 1)
        assert lp.test is None

    def test_excluded(self):
        for value, expected in zip(('', 'old', 'new'),
                                   (set(), {('A', 'B')},
                                    {('B', 'C'), ('A', 'C')})):
            lp = linkpred.LinkPred(self.config_file(training=True,
                                                    exclude=value))
            assert_equal({tuple(sorted(p)) for p in lp.excluded}, expected)
        with assert_raises(linkpred.exceptions.LinkPredError):
            lp = linkpred.LinkPred(self.config_file(exclude='bla'))
            lp.excluded

    def test_preprocess_only_training(self):
        lp = linkpred.LinkPred(self.config_file(training=True))
        lp.preprocess()
        assert_equal(set(lp.training.nodes()), set("AB"))

    def test_preprocess_training_and_test(self):
        lp = linkpred.LinkPred(self.config_file(training=True, test=True))
        lp.preprocess()
        assert_equal(set(lp.training.nodes()), {"B"})
        assert_equal(set(lp.test.nodes()), {"B"})

    @raises(linkpred.exceptions.LinkPredError)
    def test_setup_output_evaluating_without_test(self):
        lp = linkpred.LinkPred(self.config_file(training=True))
        lp.setup_output()

    def test_setup_output(self):
        # Make sure this also works is $DISPLAY is not set.
        # Should probably mock this out...
        import matplotlib
        matplotlib.use('Agg')

        for name, klass in (('recall-precision', RecallPrecisionPlotter),
                            ('f-score', FScorePlotter),
                            # Should be able to handle uppercase
                            ('ROC', ROCPlotter),
                            ('fmax', FMaxListener),
                            ('cache-evaluations', CacheEvaluationListener)):
            config = self.config_file(training=True, test=True, output=[name])
            lp = linkpred.LinkPred(config)
            lp.setup_output()
            assert_is_instance(lp.listeners[0], klass)
            smokesignal.clear_all()
        # Has an evaluator been set up?
        assert_equal(len(lp.evaluator.params['relevant']), 1)
        assert_equal(lp.evaluator.params['universe'], 2)

    def test_predict_all(self):
        # Mock out linkpred.predictors
        class Stub:
            def __init__(self, training, eligible, excluded):
                self.training = training
                self.eligible = eligible
                self.excluded = excluded

            def predict(self, **params):
                self.params = params
                return 'scoresheet'

        linkpred.predictors.A = Stub
        linkpred.predictors.B = Stub

        config = self.config_file(training=True)
        config['predictors'] = [
            {'name': 'A', 'parameters': {'X': 'x'}, 'displayname': 'prettyA'},
            {'name': 'B', 'displayname': 'prettyB'}]
        lp = linkpred.LinkPred(config)
        results = list(lp.predict_all())
        assert_equal(results, [('prettyA', 'scoresheet'),
                               ('prettyB', 'scoresheet')])

    def test_process_predictions(self):
        @smokesignal.on('prediction_finished')
        def a(scoresheet, dataset, predictor):
            assert scoresheet.startswith('scoresheet')
            assert predictor.startswith('pred')
            assert_equal(dataset, 'testing')
            a.called = True

        @smokesignal.on('dataset_finished')
        def b(dataset):
            assert_equal(dataset, 'testing')
            b.called = True

        @smokesignal.on('run_finished')
        def c():
            c.called = True

        a.called = b.called = c.called = False
        lp = linkpred.LinkPred(self.config_file())
        lp.predictions = [('pred1', 'scoresheet1'), ('pred2', 'scoresheet2')]
        lp.process_predictions()
        assert a.called
        assert b.called
        assert c.called
        smokesignal.clear_all()
