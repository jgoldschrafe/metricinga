import metricinga as m_
from metricinga import Metric, PurgedFileFactory, PurgedFileToken, \
        SourcedString
from metricinga import Actor, CarbonWriter, CarbonLineWriter, \
        CarbonPickleWriter, FileProcessor, InotifyWatcher, \
        LineProcessor, SpoolRunner
from metricinga import ParseFileRequest, ParseLineRequest, \
        PublishMetricRequest, ShutdownRequest

import nose
from nose import with_setup
from nose.tools import ok_, eq_, nottest
import os
from pprint import pprint
import shutil
import tempfile

opts = m_.parse_arguments([])
testdata_dir = os.path.sep.join([os.getcwd(), 'testdata'])

def setup_test_data():
    opts.spool_dir = tempfile.mkdtemp()
    for f in os.listdir(testdata_dir):
        old_path = os.path.sep.join([testdata_dir, f])
        new_path = os.path.sep.join([opts.spool_dir, f])
        shutil.copyfile(old_path, new_path)

def teardown_test_data():
    shutil.rmtree(opts.spool_dir)

@with_setup(setup_test_data, teardown_test_data)
def test_fileprocessor_found():
    found = []
    fp = FileProcessor(opts)
    fp.on_line_found.subscribe(found.append)
    path = os.path.sep.join([opts.spool_dir, 'host-perfdata.0'])
    fp.receive_parse(ParseFileRequest(path=path))
    eq_(len(found), 1)

@with_setup(setup_test_data, teardown_test_data)
def test_spoolrunner_find():
    found = []
    sr = SpoolRunner(opts)
    sr.on_find.subscribe(found.append)
    sr._find_files()
    eq_(len(found), 2)

def test_parse_long_args():
    args = ['--daemonize',
            '--host', 'testhost',
            '--pidfile', '/test/pidfile',
            '--poll-interval', '60',
            '--port', '62004',
            '--prefix', 'test-prefix',
            '--replacement-char', 't',
            '--spool-dir', '/test/spool-dir',
            '--verbose']
    opts = m_.parse_arguments(args)
    eq_(opts.daemonize, True)
    eq_(opts.host, 'testhost')
    eq_(opts.pidfile, '/test/pidfile')
    eq_(opts.poll_interval, 60)
    eq_(opts.port, 62004)
    eq_(opts.prefix, 'test-prefix')
    eq_(opts.replacement_char, 't')
    eq_(opts.spool_dir, '/test/spool-dir')
    eq_(opts.verbose, True)

def test_parse_short_args():
    args = ['-d',
            '-D', '/test/spool-dir',
            '-H', 'testhost',
            '-P', 'test-prefix',
            '-p', '62004',
            '-r', 't',
            '-v']
    opts = m_.parse_arguments(args)
    eq_(opts.daemonize, True)
    eq_(opts.host, 'testhost')
    eq_(opts.port, 62004)
    eq_(opts.prefix, 'test-prefix')
    eq_(opts.replacement_char, 't')
    eq_(opts.spool_dir, '/test/spool-dir')
    eq_(opts.verbose, True)
