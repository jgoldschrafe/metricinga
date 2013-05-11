import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga
from metricinga import PurgedFileToken

class PurgedFileTokenTestCase(unittest.TestCase):
    """Run unit tests for the PurgedFileToken class
    """

    @patch.object(PurgedFileToken, '__del__')
    def test_del_called(self, del_mock):
        path = '/test/mock'
        pft = PurgedFileToken(path)
        del pft
        del_mock.assert_called_once_with()

    @patch('os.remove')
    def test_del_removes_file(self, remove_mock):
        path = '/test/mock'
        pft = PurgedFileToken(path)
        pft.__del__()
        remove_mock.assert_called_once_with(path)
