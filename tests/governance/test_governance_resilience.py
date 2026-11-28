"""Governança x retry e fallback (ADRs 0005, 0006 e 0010).

Recusa de governança é decisão de política: nem o gateway (retry/fallback do router) nem a
app (SDK com max_retries=0) podem repeti-la ou desviá-la para outro modelo. Falha elegível do
provider continua sendo recuperada como antes. A parte da app roda o adapter e a API reais
em processo, apontados para o gateway real com uma chave efêmera esgotada.
"""

import importlib
import os
import sys

import pytest

from conftest import CLA_L, CLA_M, GATEWAY_URL, GPT_L, GPT_M, HELPDESK_KEY, ROOT, error_type

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"


def _fail_whole_f1_chain(gov, mode="error_500"):
    for model in (GPT_L, CLA_L, GPT_M):
        gov.fail(model, mode)


@pytest.mark.parametrize("failures", ["primario", "cadeia_inteira"])
def test_orcamento_esgotado_nao_dispara_fallback(gov, failures):
    key = gov.new_key(max_budget=0.0004)
    gov.exhaust_budget(key)
    gov.reset_provider()
    if failures == "primario":
        gov.fail(GPT_L, "error_500")
    else:
        _fail_whole_f1_chain(gov)
    response = gov.refused_without_provider_call(key)
    assert error_type(response) == "budget_exceeded"
    assert gov.calls() == []  # nem primário, nem equivalente, nem mini


def test_rpm_esgotado_nao_dispara_fallback(gov):
    key = gov.new_key(max_budget=5.0, rpm_limit=3)
    gov.exhaust_rpm(key, 3)
    gov.reset_provider()
    _fail_whole_f1_chain(gov)
    response = gov.refused_without_provider_call(key)
    assert error_type(response) == "throttling_error"
    assert gov.calls() == []


def test_falha_elegivel_do_provider_continua_com_fallback(gov):
    gov.fail(GPT_L, "error_500")
    response = gov.chat(HELPDESK_KEY)
    assert response.status_code == 200
    assert response.headers["x-litellm-attempted-fallbacks"] == "1"
    assert [(c["model"], c["status"]) for c in gov.calls()] == [
        (GPT_L, 500), (GPT_L, 500), (CLA_L, 200)]


# ------------------------------------------------------------------ app (adapter e API)


@pytest.fixture
def app_with_key(monkeypatch):
    """Carrega a app real com GATEWAY_API_KEY trocada, sem subir outro container."""
    monkeypatch.setenv("GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("GATEWAY_API_KEY", HELPDESK_KEY)
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    for name in [m for m in sys.modules if m == "helpdesk" or m.startswith("helpdesk.")]:
        del sys.modules[name]
    main = importlib.import_module("helpdesk.main")
    adapter_module = importlib.import_module("helpdesk.adapters.gateway")
    config = importlib.import_module("helpdesk.config")

    def build(key: str):
        monkeypatch.setattr(config, "GATEWAY_API_KEY", key)
        model = adapter_module.GatewayLanguageModel()
        monkeypatch.setattr(main, "language_model", model)
        return main, model

    yield build
    for name in [m for m in sys.modules if m == "helpdesk" or m.startswith("helpdesk.")]:
        del sys.modules[name]


def _complete_error(model):
    from helpdesk.ports import LanguageModelError
    with pytest.raises(LanguageModelError) as caught:
        model.complete("ticket-classification", f"TASK: classify\n{T42}")
    return caught.value


def test_app_traduz_orcamento_esgotado_sem_repetir(gov, app_with_key):
    key = gov.new_key(max_budget=0.0004)
    gov.exhaust_budget(key)
    gov.reset_provider()
    main, model = app_with_key(key)
    error = _complete_error(model)
    assert error.reason == "budget_exceeded"
    assert gov.calls() == []

    from fastapi.testclient import TestClient
    response = TestClient(main.app).post("/tickets/classification",
                                         json={"ticket_id": "TK-00042", "text": T42})
    assert response.status_code == 503
    assert response.json()["code"] == "model_budget_exceeded"
    assert "sk-" not in response.text and "0.0004" not in response.text
    assert gov.calls() == []


def test_app_traduz_rpm_esgotado_com_retry_after(gov, app_with_key):
    key = gov.new_key(max_budget=5.0, rpm_limit=3)
    gov.exhaust_rpm(key, 3)
    gov.reset_provider()
    main, model = app_with_key(key)
    error = _complete_error(model)
    assert error.reason == "throttled"
    assert error.retry_after == 60

    from fastapi.testclient import TestClient
    response = TestClient(main.app).post("/tickets/classification",
                                         json={"ticket_id": "TK-00042", "text": T42})
    assert response.status_code == 503
    assert response.json()["code"] == "model_throttled"
    assert response.headers["retry-after"] == "60"
    assert gov.calls() == []


def test_app_distingue_429_do_provider_do_429_do_gateway(gov, app_with_key):
    # Mesmo status e mesmo `type` (throttling_error) no corpo; a origem é outra.
    gov.fail(None, "error_429", provider="openai")
    gov.fail(None, "error_429", provider="anthropic")
    _, model = app_with_key(HELPDESK_KEY)
    error = _complete_error(model)
    assert error.reason == "rate_limited"
    assert [c["model"] for c in gov.calls()] == [GPT_L, CLA_L, GPT_M]


def test_app_traduz_credencial_invalida_como_recusa(gov, app_with_key):
    _, model = app_with_key("sk-chave-que-nao-existe-9999")
    assert _complete_error(model).reason == "rejected"
    assert gov.calls() == []
