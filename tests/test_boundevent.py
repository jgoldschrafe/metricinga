import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga
from metricinga import BoundEvent

class BoundEventTestCase(unittest.TestCase):
    """Run unit tests for the BoundEvent class
    """

    def test_subscribe_adds_handler(self):
        """Test that .subscribe() adds an event handler
        """
        m = MagicMock()
        be = BoundEvent()
        be.subscribe(m)
        be()
        m.assert_called_once_with()

    def test_unsubscribe_removes_handler(self):
        """Test that .unsubscribe() removes an event handler
        """
        m = MagicMock()
        be = BoundEvent()
        be.subscribe(m)
        be.unsubscribe(m)
        be()
        assert not m.called, 'was called and should not have been'
