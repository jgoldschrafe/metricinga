import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga

class ArgumentParserTestCase(unittest.TestCase):
    """Test that arguments are parsed correctly.
    """

    def test_parse_long_args(self):
        args = ['--daemonize',
                '--host', 'testhost',
                '--pidfile', '/test/pidfile',
                '--poll-interval', '60',
                '--port', '62004',
                '--prefix', 'test-prefix',
                '--replacement-char', 't',
                '--spool-dir', '/test/spool-dir',
                '--verbose']
        opts = metricinga.parse_arguments(args)
        self.assertEqual(opts.daemonize, True)
        self.assertEqual(opts.host, 'testhost')
        self.assertEqual(opts.pidfile, '/test/pidfile')
        self.assertEqual(opts.poll_interval, 60)
        self.assertEqual(opts.port, 62004)
        self.assertEqual(opts.prefix, 'test-prefix')
        self.assertEqual(opts.replacement_char, 't')
        self.assertEqual(opts.spool_dir, '/test/spool-dir')
        self.assertEqual(opts.verbose, True)

    def test_parse_short_args(self):
        args = ['-d',
                '-D', '/test/spool-dir',
                '-H', 'testhost',
                '-P', 'test-prefix',
                '-p', '62004',
                '-r', 't',
                '-v']
        opts = metricinga.parse_arguments(args)
        self.assertEqual(opts.daemonize, True)
        self.assertEqual(opts.host, 'testhost')
        self.assertEqual(opts.port, 62004)
        self.assertEqual(opts.prefix, 'test-prefix')
        self.assertEqual(opts.replacement_char, 't')
        self.assertEqual(opts.spool_dir, '/test/spool-dir')
        self.assertEqual(opts.verbose, True)
