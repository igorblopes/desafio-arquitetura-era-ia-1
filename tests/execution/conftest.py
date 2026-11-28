"""Infraestrutura dos testes de execução síncrona (Passo 13, ADR 0011).

Dois tipos de teste, com fronteiras diferentes:

1. Integração pela BORDA (test_sync_*.py): app real, gateway real, provider-fake real, tudo
   do docker compose, medido em http://localhost:8000. É a evidência dos requisitos de
   latência (3 s normal na F1, 15 s sob travamento) e da ausência de 504 da borda. As
   chamadas reais vêm de /admin/calls. O provider é estado global: a suíte roda em
   sequência e cada teste começa e termina com /admin/reset.

2. Contrato de saída EM PROCESSO (test_output_contract.py, test_deadline.py): o código real
   das features e do adapter, com um modelo de linguagem substituto ou um "gateway" que
   aceita a conexão e nunca responde. Cobre o que o simulador não produz (ele é
   determinístico e sempre devolve JSON bem formado) e o deadline da app sem precisar
   congelar o container do gateway.
"""

import importlib
import os
import pathlib
import sys
import time

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER_URL = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")

GPT_L, CLA_L, GPT_M, CLA_M = "gpt-fake-large", "claude-fake-large", "gpt-fake-mini", "claude-fake-mini"
PROVIDER_OF = {GPT_L: "openai", GPT_M: "openai", CLA_L: "anthropic", CLA_M: "anthropic"}
MINI = {GPT_M, CLA_M}

# Requisitos do enunciado (medidos pela borda).
F1_NORMAL_LIMIT = 3.0       # F1, resultado completo em modo normal
SYNC_FAILURE_LIMIT = 15.0   # qualquer feature síncrona com provider travado: sucesso ou erro explícito

CATEGORIES = {"delivery", "payment", "exchange_return", "product_defect", "other"}
PRIORITIES = {"low", "medium", "high"}
ORDER_RE = r"#[0-9]{6}"

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"


class Edge:
    """Cliente da borda + administração do provider-fake."""

    def __init__(self) -> None:
        # Maior que os 30 s da borda: se a borda der 504, o teste vê o 504 (não um timeout dele).
        self.client = httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(45.0, connect=5.0))
        self.provider = httpx.Client(base_url=PROVIDER_URL, timeout=10.0)

    def reset(self) -> None:
        self.provider.post("/admin/reset").raise_for_status()

    def fail(self, model: str | None, mode: str, provider: str | None = None) -> None:
        body = {"provider": provider or PROVIDER_OF[model], "mode": mode}
        if model is not None:
            body["model"] = model
        self.provider.post("/admin/failures", json=body).raise_for_status()

    def calls(self, task: str) -> list[dict]:
        body = self.provider.get("/admin/calls", params={"last": 200}).json()
        return sorted((c for c in body if c["task"] == task), key=lambda c: c["ts"])

    def all_calls(self) -> int:
        return len(self.provider.get("/admin/calls", params={"last": 500}).json())

    def post(self, path: str, body: dict) -> tuple[httpx.Response, float]:
        start = time.perf_counter()
        response = self.client.post(path, json=body)
        return response, time.perf_counter() - start


def explicit_app_error(response: httpx.Response, status: int, code: str) -> None:
    """Erro explícito da APP: JSON {"detail", "code"}; nunca o HTML do 504 do nginx."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json"), response.text
    assert response.json()["code"] == code
    assert "Traceback" not in response.text and "sk-" not in response.text


@pytest.fixture(scope="session")
def _edge() -> Edge:
    edge = Edge()
    try:
        edge.client.get("/health").raise_for_status()
        edge.reset()
    except httpx.HTTPError as error:
        pytest.exit(f"Suba o ambiente antes (docker compose up -d --wait): {error}", returncode=2)
    return edge


@pytest.fixture
def edge(_edge: Edge):
    _edge.reset()
    yield _edge
    _edge.reset()


# ------------------------------------------------------------------ app em processo

@pytest.fixture
def helpdesk(monkeypatch):
    """Importa a app REAL (app/helpdesk) em processo, com um gateway apontado por variável.

    Nenhuma chamada sai daqui a menos que o teste aponte GATEWAY_URL para algo que escute.
    """
    monkeypatch.setenv("GATEWAY_URL", os.environ.get("EXEC_TEST_GATEWAY_URL", "http://127.0.0.1:9"))
    monkeypatch.setenv("GATEWAY_API_KEY", "sk-teste-sem-uso")
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    _forget_helpdesk()
    yield importlib.import_module("helpdesk.main")
    _forget_helpdesk()


def _forget_helpdesk() -> None:
    for name in [m for m in sys.modules if m == "helpdesk" or m.startswith("helpdesk.")]:
        del sys.modules[name]
