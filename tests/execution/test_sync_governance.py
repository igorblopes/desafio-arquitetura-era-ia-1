"""Recusas de governança nas rotas síncronas F1 e F4 (app real em processo, gateway real).

tests/governance já prova a recusa no gateway e a tradução na F1. Aqui o foco é a rota
SÍNCRONA das duas features: a recusa chega como erro explícito da app (503/502 com `code`),
imediata, sem retry, sem fallback e sem nenhuma chamada nova ao provider. A chave do
helpdesk nunca é consumida: cada teste cria a sua chave efêmera (com a master key, papel do
provisionamento) e a apaga no fim. O mesmo cenário pela borda, com a app recriada com a
chave esgotada, está em docs/execucao/evidencias/11-governanca-*.json.
"""

import os
import pathlib
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
ROUTES = {"F1": ("/tickets/classification", "TASK: classify\n", "ticket-classification"),
          "F4": ("/tickets/extraction", "TASK: extract\n", "order-extraction")}
T = "Pedido #481516, o fone de ouvido bluetooth veio com chiado, urgente"


def _master_key() -> str:
    path = ROOT / ".env" if (ROOT / ".env").exists() else ROOT / ".env.example"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GATEWAY_MASTER_KEY="):
            return os.environ.get("GATEWAY_MASTER_KEY", line.split("=", 1)[1].strip())
    raise RuntimeError("GATEWAY_MASTER_KEY não encontrada")


@pytest.fixture
def keys():
    admin = httpx.Client(base_url=GATEWAY_URL, timeout=30.0,
                         headers={"Authorization": f"Bearer {_master_key()}"})
    created: list[str] = []

    def new(**policy) -> str:
        key = f"sk-test-execution-{uuid.uuid4().hex[:12]}"
        response = admin.post("/key/generate", json={
            "key": key, "key_alias": f"test-execution-{key[-12:]}",
            "models": [r[2] for r in ROUTES.values()], **policy})
        assert response.status_code == 200, response.text
        created.append(key)
        return key

    yield new
    admin.post("/key/delete", json={"keys": created})
    admin.close()


def _direct(key: str, feature: str) -> int:
    _, prefix, capability = ROUTES[feature]
    return httpx.post(f"{GATEWAY_URL}/v1/chat/completions", timeout=30.0,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": capability, "messages": [{"role": "user", "content": prefix + T}]}
                      ).status_code


def _exhaust_budget(key: str) -> None:
    """Chama até recusar (pausa entre chamadas: o LiteLLM reserva o custo máximo em voo)."""
    for _ in range(8):
        time.sleep(1.0)
        if _direct(key, "F1") != 200:
            time.sleep(1.0)
            if _direct(key, "F1") != 200:
                return
    raise AssertionError("o orçamento não esgotou")


def _through_app(helpdesk, monkeypatch, key: str, feature: str, edge) -> tuple:
    from helpdesk import config
    from helpdesk.adapters.gateway import GatewayLanguageModel
    monkeypatch.setattr(config, "GATEWAY_API_KEY", key)
    monkeypatch.setattr(helpdesk, "language_model", GatewayLanguageModel())
    before = edge.all_calls()
    start = time.perf_counter()
    response = TestClient(helpdesk.app).post(ROUTES[feature][0], json={"ticket_id": "TK-1", "text": T})
    elapsed = time.perf_counter() - start
    time.sleep(0.5)
    return response, elapsed, edge.all_calls() - before


@pytest.fixture
def app_on_gateway(monkeypatch):
    monkeypatch.setenv("EXEC_TEST_GATEWAY_URL", GATEWAY_URL)


@pytest.mark.parametrize("feature", ["F1", "F4"])
def test_orcamento_esgotado_recusa_imediata_sem_chamar_provider(app_on_gateway, helpdesk, monkeypatch,
                                                                edge, keys, feature):
    key = keys(max_budget=0.0004)
    _exhaust_budget(key)
    edge.fail(None, "error_500", provider="openai")   # nem com o primário em falha há fallback
    response, elapsed, new_calls = _through_app(helpdesk, monkeypatch, key, feature, edge)

    assert response.status_code == 503
    assert response.json()["code"] == "model_budget_exceeded"
    assert new_calls == 0
    assert elapsed < 1.0   # decisão de política: não espera timeout nem backoff


@pytest.mark.parametrize("feature", ["F1", "F4"])
def test_rpm_esgotado_recusa_com_retry_after_sem_chamar_provider(app_on_gateway, helpdesk, monkeypatch,
                                                                 edge, keys, feature):
    key = keys(max_budget=1.0, rpm_limit=2)
    assert [_direct(key, feature) for _ in range(2)] == [200, 200]
    response, elapsed, new_calls = _through_app(helpdesk, monkeypatch, key, feature, edge)

    assert response.status_code == 503
    assert response.json()["code"] == "model_throttled"
    assert response.headers["retry-after"] == "60"
    assert new_calls == 0
    assert elapsed < 1.0


@pytest.mark.parametrize("feature", ["F1", "F4"])
def test_credencial_invalida_vira_recusa_sem_trocar_de_chave(app_on_gateway, helpdesk, monkeypatch,
                                                             edge, feature):
    response, _, new_calls = _through_app(helpdesk, monkeypatch, "sk-chave-inexistente-0000", feature, edge)

    assert response.status_code == 502
    assert response.json() == {"detail": "A requisição ao modelo foi recusada.", "code": "model_rejected"}
    assert "sk-" not in response.text
    assert new_calls == 0
