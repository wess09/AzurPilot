from collections import deque

from module.server_checker import ServerChecker


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.trust_env = True
        self.calls = []

    def post(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.responses.pop(0)


def make_checker(server='长弓计划'):
    checker = ServerChecker.__new__(ServerChecker)
    checker._base = 'http://sc.shiratama.cn'
    checker._api = {
        'get_state': '/server/get_state',
        'get_all_state': '/server/get_all_state',
        'list': '/server/list',
    }
    checker._server = server
    checker._state = deque(maxlen=2)
    checker._timestamp = 0
    checker._expired = 0
    checker._recover = False
    checker._retry = False
    return checker


def test_404_single_state_uses_all_state_maintenance_fallback(monkeypatch):
    checker = make_checker()
    session = FakeSession([
        FakeResponse(404, {'detail': 'Server name does not exist!'}),
        FakeResponse(200, {'长弓计划': 1}),
    ])
    monkeypatch.setattr('module.server_checker.requests.Session', lambda: session)

    checker._load_server()

    assert checker._state[-1] is False
    assert session.calls[0][0].endswith('/server/get_state')
    assert session.calls[1][0].endswith('/server/get_all_state')


def test_404_single_state_uses_all_state_available_fallback(monkeypatch):
    checker = make_checker()
    session = FakeSession([
        FakeResponse(404, {'detail': 'Server name does not exist!'}),
        FakeResponse(200, {'长弓计划': 0}),
    ])
    monkeypatch.setattr('module.server_checker.requests.Session', lambda: session)

    checker._load_server()

    assert checker._state[-1] is True


def test_404_full_state_is_trusted_even_when_local_list_is_stale(monkeypatch):
    checker = make_checker()
    session = FakeSession([
        FakeResponse(404, {'detail': 'Server name does not exist!'}),
        FakeResponse(200, {'长弓计划': 0}),
    ])
    monkeypatch.setattr('module.server_checker.requests.Session', lambda: session)
    monkeypatch.setattr(checker, '_server_in_local_list', lambda: False)

    checker._load_server()

    assert checker._state[-1] is True


def test_timestamp_missing_in_fallback_does_not_expire_api():
    checker = make_checker()

    checker._apply_timestamp(None)

    assert checker._timestamp == 0
    assert checker._expired == 0
