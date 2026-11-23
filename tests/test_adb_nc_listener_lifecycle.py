"""ADB_nc 监听清理回归，使用本机套接字且不连接 Android 设备。"""

import socket
import unittest
from unittest.mock import PropertyMock, patch

from module.device.connection import Connection


class NcListenerLifecycleTests(unittest.TestCase):
    def test_release_closes_cached_listener_even_when_still_referenced(self):
        connection = Connection.__new__(Connection)
        with patch.object(Connection, '_nc_server_host_port', new_callable=PropertyMock,
                          return_value=('127.0.0.1', 0, '127.0.0.1', 7903)):
            listener = connection.reverse_server

        address = listener.getsockname()
        connection.release_resource()
        connection.release_resource()

        self.assertEqual(listener.fileno(), -1)
        self.assertNotIn('reverse_server', connection.__dict__)
        with socket.socket() as replacement:
            replacement.bind(address)
            replacement.listen()

    def test_bind_failure_closes_attempt_without_affecting_existing_listener(self):
        connection = Connection.__new__(Connection)
        with socket.socket() as occupied, socket.socket() as attempt:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            address = occupied.getsockname()
            with patch.object(Connection, '_nc_server_host_port', new_callable=PropertyMock,
                              return_value=(*address, '127.0.0.1', 7903)):
                with patch('module.device.connection.socket.socket', return_value=attempt):
                    with self.assertRaises(OSError):
                        _ = connection.reverse_server

            self.assertEqual(attempt.fileno(), -1)
            self.assertNotIn('reverse_server', connection.__dict__)
            with socket.create_connection(address, timeout=2):
                accepted, _ = occupied.accept()
                accepted.close()
