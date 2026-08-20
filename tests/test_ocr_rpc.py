import sys
import types
import unittest
from unittest.mock import Mock, patch

from module.device.device import Device
from module.ocr import rpc
from module.ocr.rpc import ModelProxy, wait_for_ocr_server


class FakeRpcClient:
    def __init__(self, timeout, *, hello_error=False, call_error=False):
        self.timeout = timeout
        self.hello_error = hello_error
        self.call_error = call_error
        self.address = None
        self.closed = False

    def connect(self, address):
        self.address = address

    def hello(self):
        if self.hello_error:
            raise RuntimeError('服务未就绪')
        return 'hello'

    def close(self):
        self.closed = True

    def __call__(self, method, *args):
        if self.call_error:
            raise RuntimeError('连接已断开')
        return (method, args)


class TestModelProxy(unittest.TestCase):
    def setUp(self):
        self.original_client = ModelProxy.client
        self.original_address = ModelProxy._address
        self.original_retry_at = ModelProxy._next_retry_at
        ModelProxy.client = None
        ModelProxy._address = None
        ModelProxy._next_retry_at = 0.0

    def tearDown(self):
        ModelProxy.close()
        ModelProxy.client = self.original_client
        ModelProxy._address = self.original_address
        ModelProxy._next_retry_at = self.original_retry_at

    def test_failed_handshake_can_connect_again(self):
        failed = FakeRpcClient(5, hello_error=True)
        connected = FakeRpcClient(5)
        clients = [failed, connected]
        rpc_module = types.SimpleNamespace(Client=lambda timeout: clients.pop(0))

        with patch.dict(sys.modules, {'zerorpc': rpc_module}):
            self.assertFalse(ModelProxy.init('127.0.0.1:30001'))
            self.assertIsNone(ModelProxy.client)

            self.assertTrue(ModelProxy.init('127.0.0.1:30001'))

        self.assertTrue(failed.closed)
        self.assertIs(ModelProxy.client, connected)

    def test_failed_request_closes_client_for_later_reconnect(self):
        failed = FakeRpcClient(5, call_error=True)
        connected = FakeRpcClient(5)
        clients = [failed, connected]
        rpc_module = types.SimpleNamespace(Client=lambda timeout: clients.pop(0))

        with patch.dict(sys.modules, {'zerorpc': rpc_module}):
            self.assertTrue(ModelProxy.init('127.0.0.1:30002'))
            result = ModelProxy._call('127.0.0.1:30002', 'ocr', 'payload')

            self.assertIs(result, ModelProxy._unavailable)
            self.assertIsNone(ModelProxy.client)
            self.assertTrue(ModelProxy.init('127.0.0.1:30002'))

        self.assertTrue(failed.closed)
        self.assertIs(ModelProxy.client, connected)

    def test_wait_for_server_uses_hello_probe(self):
        client = FakeRpcClient(1)
        rpc_module = types.SimpleNamespace(Client=lambda timeout: client)

        with patch.dict(sys.modules, {'zerorpc': rpc_module}):
            self.assertTrue(
                wait_for_ocr_server('127.0.0.1:30003', timeout=0.1)
            )

        self.assertEqual('tcp://127.0.0.1:30003', client.address)
        self.assertTrue(client.closed)

    def test_remote_ocr_skips_local_benchmark(self):
        device = object.__new__(Device)
        with patch('module.device.device._use_ocr_server', return_value=True):
            self.assertIsNone(device.run_simple_ocr_benchmark())


class TestOcrServerProcess(unittest.TestCase):
    def setUp(self):
        self.original_process = rpc.process
        self.original_port = rpc.process_port

    def tearDown(self):
        rpc.process = self.original_process
        rpc.process_port = self.original_port

    def test_port_change_restarts_managed_server(self):
        created = Mock()
        rpc.process_port = 30005

        with (
            patch.object(rpc, 'alive', side_effect=[True, True]),
            patch.object(rpc, 'stop_ocr_server_process') as stop_server,
            patch.object(rpc.multiprocessing, 'Process', return_value=created) as process,
        ):
            rpc.start_ocr_server_process(30006)

        stop_server.assert_called_once_with()
        process.assert_called_once_with(target=rpc.start_ocr_server, args=(30006,))
        created.start.assert_called_once_with()
        self.assertIs(rpc.process, created)
        self.assertEqual(30006, rpc.process_port)
