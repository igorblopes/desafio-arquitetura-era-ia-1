"""Infraestrutura dos testes de fallback (Passo 11, ADR 0006).

Integração real: borda (8000), app, gateway e provider-fake (8090) do docker compose. Os
modos de falha são estado global do provider, então a suíte roda em sequência (sem
pytest-xdist) e cada teste começa e termina com o provider resetado.

Cuidado com cadeias órfãs: quando a app desiste no prazo, o gateway continua a cadeia por
conta própria (o LiteLLM não tem deadline por requisição). Por isso `calls(feature)` filtra
pela tarefa da feature e os testes que criam órfãos esperam a cadeia terminar.
"""

import json
import os
import pathlib
import threading
import time

import httpx
import pytest

BASE_URL = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER_URL = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")
EXPECTED = pathlib.Path(__file__).resolve().parents[1] / "characterization" / "expected"

GPT_L, CLA_L, GPT_M, CLA_M = "gpt-fake-large", "claude-fake-large", "gpt-fake-mini", "claude-fake-mini"
PROVIDER_OF = {GPT_L: "openai", GPT_M: "openai", CLA_L: "anthropic", CLA_M: "anthropic"}
LARGE = {GPT_L, CLA_L}
MINI = {GPT_M, CLA_M}

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"


def _golden(name: str) -> dict:
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))["body"]


# Política decidida no ADR 0006: (rota, corpo, tarefa, cadeia de modelos físicos, resposta
# esperada em sucesso). A cadeia é a ordem de recuperação; o 3º item só existe se o produto
# aceitou um modelo inferior.
FEATURES = {
    "F1": ("/tickets/classification", {"ticket_id": "TK-00042", "text": T42}, "classify",
           [GPT_L, CLA_L, GPT_M],
           {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}),
    "F2": ("/tickets/reply-suggestion", {"ticket_id": "TK-00042", "text": T42}, "suggest",
           [CLA_L, GPT_L, CLA_M], _golden("reply_suggestion_TK-00042.json")),
    "F3": ("/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}, "topics",
           [CLA_L, GPT_L], _golden("topics_2026-08-01.json")),
    "F4": ("/tickets/extraction", {"ticket_id": "TK-00200", "text": T200}, "extract",
           [GPT_L, CLA_L],
           {"ticket_id": "TK-00200", "order_number": "#481516", "product": "fone de ouvido bluetooth"}),
}
# Tentativas máximas por destino (ADR 0006): primário 2 em 500/503, 1 nos demais erros;
# equivalente 1; inferior 1.
PRIMARY_ATTEMPTS_500 = 2


def chain(feature: str) -> list[str]:
    return FEATURES[feature][3]


class Stack:
    def __init__(self) -> None:
        self.edge = httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(45.0, connect=5.0))
        self.provider = httpx.Client(base_url=PROVIDER_URL, timeout=10.0)

    def reset(self) -> None:
        self.provider.post("/admin/reset").raise_for_status()

    def fail(self, model: str | None, mode: str, provider: str | None = None) -> None:
        """Falha num modelo (os outros do provider seguem normais) ou, sem modelo, no provider."""
        body = {"provider": provider or PROVIDER_OF[model], "mode": mode}
        if model is not None:
            body["model"] = model
        self.provider.post("/admin/failures", json=body).raise_for_status()

    def fail_both_large(self, mode: str = "error_500") -> None:
        self.fail(GPT_L, mode)
        self.fail(CLA_L, mode)

    def fail_both_providers(self, mode: str) -> None:
        self.fail(None, mode, provider="openai")
        self.fail(None, mode, provider="anthropic")

    def calls(self, feature: str | None = None) -> list[dict]:
        body = self.provider.get("/admin/calls", params={"last": 200}).json()
        body = body["calls"] if isinstance(body, dict) else body
        if feature is not None:
            body = [c for c in body if c["task"] == FEATURES[feature][2]]
        return sorted(body, key=lambda c: c["ts"])

    def sequence(self, feature: str) -> list[tuple[str, int]]:
        return [(c["model"], c["status"]) for c in self.calls(feature)]

    def run(self, feature: str, body: dict | None = None) -> tuple[httpx.Response, float]:
        route, default, *_ = FEATURES[feature]
        start = time.monotonic()
        response = self.edge.post(route, json=body or default)
        return response, time.monotonic() - start

    def wait_chain_end(self, feature: str, expected_calls: int, limit: float) -> None:
        """Espera a cadeia órfã do gateway registrar `expected_calls` chamadas (ou o limite)."""
        deadline = time.monotonic() + limit
        while len(self.calls(feature)) < expected_calls and time.monotonic() < deadline:
            time.sleep(0.5)

    def run_failing_after_first_call(self, feature: str, model: str, mode: str,
                                     body: dict) -> tuple[httpx.Response, float]:
        """Liga a falha no `model` assim que a 1ª chamada da feature CHEGA ao provider.

        O provider decide o modo no recebimento: a 1ª chamada (já recebida) segue normal e
        só as seguintes falham. Na F3 isso quer dizer: 1º lote no primário, 2º em falha.
        """
        result: list = []
        request = threading.Thread(target=lambda: result.append(self.run(feature, body)))
        request.start()
        limit = time.monotonic() + 20
        while not self.calls(feature) and time.monotonic() < limit:
            time.sleep(0.05)
        self.fail(model, mode)
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
