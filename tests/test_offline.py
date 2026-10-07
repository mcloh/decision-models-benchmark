import os
import socket

import pytest

from dmb.offline import NetworkAccessBlocked, enforce_offline, self_test


def test_external_connection_is_blocked():
    enforce_offline()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    s = socket.socket()
    try:
        with pytest.raises(NetworkAccessBlocked):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()


def test_loopback_is_allowed():
    enforce_offline()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket()
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def test_self_test_reports_guard():
    enforce_offline()
    assert self_test()["process_guard"].startswith("ok")
