import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga
from metricinga import Metric

class MetricTestCase(unittest.TestCase):
    """Run unit tests for the Metric class
    """

    def test_sets_attributes(self):
        """Test that the Metric initializer sets arguments correctly
        """
        path = 'example.path'
        timestamp = 3704558
        value = 8675309
        source = 'test_source'

        # Set positional arguments
        m = Metric(path, timestamp, value, source)
        self.assertEqual(m.path, path)
        self.assertEqual(m.timestamp, timestamp)
        self.assertEqual(m.value, value)
        self.assertEqual(m.source, source)

        # Set keyword arguments
        m = Metric(path=path, timestamp=timestamp, value=value,
                   source=source)
        self.assertEqual(m.path, path)
        self.assertEqual(m.timestamp, timestamp)
        self.assertEqual(m.value, value)
        self.assertEqual(m.source, source)
