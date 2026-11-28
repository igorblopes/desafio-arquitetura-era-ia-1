"""Contabilização: preço do modelo físico que respondeu, por chave (ADR 0010)."""

import pytest

from conftest import F1, F1_COST, GPT_L, MASTER_KEY, cost

# Um grupo por modelo físico; a chamada curta de classificação serve para todos.
GROUPS = {"ticket-classification": "gpt-fake-large", "reply-suggestion": "claude-fake-large",
          "ticket-classification-degraded": "gpt-fake-mini",
          "reply-suggestion-degraded": "claude-fake-mini"}


@pytest.mark.parametrize("group,model", GROUPS.items())
def test_custo_registrado_igual_ao_calculo_manual(gov, group, model):
    response = gov.chat(MASTER_KEY, group)
    assert response.status_code == 200
    call = gov.calls()[-1]
    assert call["model"] == model
    expected = cost(model, call["input_tokens"], call["output_tokens"])
    registered = float(response.headers["x-litellm-response-cost"])
    assert expected > 0
    assert registered == pytest.approx(expected, rel=1e-9)


def test_gasto_acumulado_na_chave(gov):
    key = gov.new_key(max_budget=1.0)
    for _ in range(2):
        assert gov.chat(key).status_code == 200
    assert gov.wait_spend(key, 2 * F1_COST) == pytest.approx(2 * F1_COST, rel=1e-9)


def test_fallback_cobra_so_o_destino_que_respondeu(gov):
    # Primário 500 (2 tentativas sem usage) -> claude-fake-large responde: paga o preço dele.
    key = gov.new_key(max_budget=1.0)
    gov.fail(GPT_L, "error_500")
    response = gov.chat(key)
    assert response.status_code == 200
    calls = gov.calls()
    assert [(c["model"], c["status"]) for c in calls] == [
        (GPT_L, 500), (GPT_L, 500), ("claude-fake-large", 200)]
    answered = calls[-1]
    expected = cost("claude-fake-large", answered["input_tokens"], answered["output_tokens"])
    assert float(response.headers["x-litellm-response-cost"]) == pytest.approx(expected, rel=1e-9)
    assert gov.wait_spend(key, expected) == pytest.approx(expected, rel=1e-9)
