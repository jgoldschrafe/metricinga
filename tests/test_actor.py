import mock
from mock import MagicMock
from mock import patch
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..')))

import metricinga
from metricinga import Actor, ShutdownRequest

class ActorTestCase(unittest.TestCase):
    """Run unit tests for the Actor class
    """

    @patch.object(Actor, 'receive_shutdown')
    def test_send_and_receive(self, rs_mock):
        """Test that the Actor can send and receive messages
        """
        actor = Actor()
        msg1 = ShutdownRequest()
        actor.send(msg1)
        (prio, msg2) = actor.inbox.get()
        self.assertEqual(msg1, msg2)

        actor.receive(msg2)
        rs_mock.assert_called_once_with(msg2)
