import socket

import pytest


@pytest.fixture(autouse=True)
def offline_network_guard(monkeypatch, request):
    """Fail accidental network calls; HTTPX ASGI/MockTransport remain in process."""
    if request.node.get_closest_marker("live"):
        pytest.skip("Use the separately approved live evaluator; pytest makes no paid calls.")
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Network access is disabled in offline tests")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
