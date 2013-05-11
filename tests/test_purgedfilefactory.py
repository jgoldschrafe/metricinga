import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga
from metricinga import PurgedFileFactory

@patch('metricinga.PurgedFileToken')
class PurgedFileFactoryTestCase(unittest.TestCase):
    """Run unit tests for the PurgedFileFactory class
    """

    def setUp(self):
        self.path = '/test/path'
        self.i1 = PurgedFileFactory.create(self.path)
        self.i2 = PurgedFileFactory.create(self.path)

    #@patch('metricinga.PurgedFileToken')
    def test_create(self, pft_mock):
        """Test that create() has appropriate singleton-like behavior
        """
        self.assertNotEqual(self.i1, None)
        self.assertEqual(self.i2, None)

    #@patch('metricinga.PurgedFileToken')
    def test_destroy(self, pft_mock):
        """Test that destroy() purges token singletons
        """
        PurgedFileFactory.destroy(self.path)
        i3 = PurgedFileFactory.create(self.path)
        self.assertNotEqual(i3, None)
