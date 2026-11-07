import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests never hit the network (rule 10)."""

    def guard(*args, **kwargs):
        raise RuntimeError("network access attempted in a test")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
