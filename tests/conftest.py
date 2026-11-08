import os
import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests never hit the network (rule 10). NMT_VCR_RECORD=1 lifts this to record cassettes."""
    if os.environ.get("NMT_VCR_RECORD") == "1":
        return

    def guard(*args, **kwargs):
        raise RuntimeError("network access attempted in a test")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
