"""Infraestrutura dos testes de resiliência (Passo 10, ADR 0005).

Integração real: aplicação, borda (porta 8000), gateway e provider-fake do docker compose.
O modo de falha é estado global do provider, então a suíte roda em sequência (sem
pytest-xdist) e cada teste começa e termina com o provider resetado.

Variáveis de ambiente: HELPDESK_BASE_URL e PROVIDER_ADMIN_URL (as mesmas da caracterização).
"""

import os
import threading
import time

import httpx
import pytest

BASE_URL = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER_URL = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")
TEXT = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
TICKET = {"ticket_id": "TK-00042", "text": TEXT}

# feature -> (rota, corpo, provider e modelo físico que o gateway usa para ela)
FEATURES = {
    "F1": ("/tickets/classification", TICKET, "openai", "gpt-fake-large"),
    "F2": ("/tickets/reply-suggestion", TICKET, "anthropic", "claude-fake-large"),
    "F3": ("/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}, "anthropic",
           "claude-fake-large"),
    "F4": ("/tickets/extraction", TICKET, "openai", "gpt-fake-large"),
}


class Stack:
    def __init__(self) -> None:
        self.edge = httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(40.0, connect=5.0))
        self.provider = httpx.Client(base_url=PROVIDER_URL, timeout=10.0)

    def reset(self) -> None:
        self.provider.post("/admin/reset").raise_for_status()

    def set_mode(self, feature: str, mode: str) -> None:
        _, _, provider, model = FEATURES[feature]
        self.provider.post(
            "/admin/failures", json={"provider": provider, "model": model, "mode": mode}
        ).raise_for_status()

    def calls(self) -> list[dict]:
        body = self.provider.get("/admin/calls", params={"last": 50}).json()
        body = body["calls"] if isinstance(body, dict) else body
        return sorted(body, key=lambda c: c["ts"])

    def run(self, feature: str) -> tuple[httpx.Response, float]:
        route, body, _, _ = FEATURES[feature]
        start = time.monotonic()
        response = self.edge.post(route, json=body)
        return response, time.monotonic() - start

    def run_recovering(self, feature: str, mode: str) -> tuple[httpx.Response, float]:
        """Liga a falha e volta ao normal assim que a 1ª tentativa chega ao provider."""
        self.set_mode(feature, mode)
        result: list = []
        request = threading.Thread(target=lambda: result.append(self.run(feature)))
        request.start()
        limit = time.monotonic() + 10
        while not self.calls() and time.monotonic() < limit:
            time.sleep(0.02)
        self.set_mode(feature, "normal")  # sem /admin/reset: o registro é a evidência
        request.join()
        return result[0]


@pytest.fixture(scope="session")
def _stack() -> Stack:
    stack = Stack()
    try:
        stack.edge.get("/health").raise_for_status()
        stack.reset()
    except httpx.HTTPError as error:
        pytest.exit(f"Suba o ambiente antes (docker compose up -d --wait): {error}", returncode=2)
    return stack


@pytest.fixture
def stack(_stack: Stack):
    _stack.reset()
    yield _stack
    _stack.reset()
