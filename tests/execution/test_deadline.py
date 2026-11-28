"""Deadline global da app para F1 e F4 com um gateway que aceita a conexão e nunca responde.

É o caso que nenhum timeout do gateway cobre (o próprio gateway travado ou congelado): só o
limite da app (config.GATEWAY_DEADLINE_SECONDS, 14 s) encerra a espera, com erro explícito
antes dos 15 s do enunciado e dos 30 s da borda. Pela borda, o mesmo cenário está em
docs/execucao/evidencias/13-gateway-congelado-deadline.json (docker compose pause gateway).
"""

import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import SYNC_FAILURE_LIMIT, T42


@pytest.fixture
def silent_gateway(monkeypatch):
    """Servidor TCP que aceita conexões, lê e nunca escreve nada."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                connection, _ = server.accept()
                accepted.append(connection)
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    monkeypatch.setenv("EXEC_TEST_GATEWAY_URL", f"http://127.0.0.1:{server.getsockname()[1]}")
    yield accepted
    stop.set()
    thread.join()
    for connection in accepted:
        connection.close()
    server.close()


@pytest.mark.parametrize("route, capability", [
    ("/tickets/classification", "ticket-classification"),
    ("/tickets/extraction", "order-extraction"),
])
def test_gateway_mudo_termina_no_deadline_da_app(silent_gateway, helpdesk, route, capability):
    from helpdesk import config
    deadline = config.GATEWAY_DEADLINE_SECONDS[capability]
    assert deadline < SYNC_FAILURE_LIMIT  # o limite é explícito e cabe no requisito

    client = TestClient(helpdesk.app, raise_server_exceptions=False)
    start = time.perf_counter()
    response = client.post(route, json={"ticket_id": "TK-00042", "text": T42})
    elapsed = time.perf_counter() - start

    assert len(silent_gateway) == 1          # uma única conexão: o SDK não repete (max_retries=0)
    assert response.status_code == 503
    assert response.json() == {"detail": "O modelo não respondeu dentro do prazo.", "code": "model_timeout"}
    assert deadline - 0.5 <= elapsed < SYNC_FAILURE_LIMIT, elapsed
