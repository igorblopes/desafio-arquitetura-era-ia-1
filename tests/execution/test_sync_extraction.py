"""F4 síncrona pela borda: contrato, nulos legítimos e resposta limitada sob falha.

O enunciado não fixa 3 s para a F4 (só a F1 tem esse requisito); o que vale é o limite de
15 s com o provider travado e nunca um sucesso fictício. Modelo inferior é PROIBIDO na F4
(ADR 0006): o mini nunca pode aparecer em /admin/calls.
"""

import re

import pytest

from conftest import CLA_L, GPT_L, MINI, ORDER_RE, SYNC_FAILURE_LIMIT, T200, explicit_app_error

ROUTE = "/tickets/extraction"
TASK = "extract"
BODY = {"ticket_id": "TK-00200", "text": T200}
EXPECTED = {"ticket_id": "TK-00200", "order_number": "#481516", "product": "fone de ouvido bluetooth"}

# Resultados observados no simulador (docs/execucao/evidencias/02-normal-f4.json).
INPUTS = [
    pytest.param("TK-00200", T200, "#481516", "fone de ouvido bluetooth", id="pedido-e-produto"),
    pytest.param("TK-00201", "O protocolo #12345 não resolveu, o aspirador robô continua sem funcionar",
                 None, "aspirador robô", id="pedido-ausente"),
    pytest.param("TK-00042", "Meu pedido #481516 não chegou e já passou do prazo, urgente",
                 "#481516", None, id="produto-ausente"),
    pytest.param("TK-00202", "Como faço para alterar meu e-mail de cadastro?", None, None,
                 id="ambos-ausentes"),
    # Exemplo do enunciado: o simulador só conhece "teclado mecânico", então "teclado" -> null.
    pytest.param("TK-00042", "Quero devolver o teclado do pedido #481516.", "#481516", None,
                 id="exemplo-do-enunciado"),
]


@pytest.mark.parametrize("ticket_id, text, order_number, product", INPUTS)
def test_extracao_completa_no_primario(edge, ticket_id, text, order_number, product):
    response, elapsed = edge.post(ROUTE, {"ticket_id": ticket_id, "text": text})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"ticket_id", "order_number", "product"}   # nulos vêm explícitos
    assert body["order_number"] is None or re.fullmatch(ORDER_RE, body["order_number"])
    assert body["product"] is None or isinstance(body["product"], str)
    assert body == {"ticket_id": ticket_id, "order_number": order_number, "product": product}
    assert elapsed < SYNC_FAILURE_LIMIT
    assert [(c["model"], c["status"]) for c in edge.calls(TASK)] == [(GPT_L, 200)]


def test_entrada_invalida_nao_chama_o_modelo(edge):
    response, _ = edge.post(ROUTE, {"ticket_id": "TK-1", "text": ""})
    assert response.status_code == 422
    assert edge.calls(TASK) == []


def test_primario_500_recupera_pelo_large_equivalente(edge):
    edge.fail(GPT_L, "error_500")
    response, elapsed = edge.post(ROUTE, BODY)

    assert response.status_code == 200 and response.json() == EXPECTED   # valores preservados
    assert elapsed < SYNC_FAILURE_LIMIT
    assert [(c["model"], c["status"]) for c in edge.calls(TASK)] == [(GPT_L, 500), (GPT_L, 500), (CLA_L, 200)]


def test_primario_travado_responde_pelo_fallback_em_menos_de_15s(edge):
    edge.fail(GPT_L, "timeout")
    response, elapsed = edge.post(ROUTE, BODY)

    assert response.status_code == 200 and response.json() == EXPECTED
    assert elapsed < SYNC_FAILURE_LIMIT, f"{elapsed:.3f} s"
    assert [c["model"] for c in edge.calls(TASK)] == [GPT_L, CLA_L]


def test_dois_large_fora_falha_explicita_sem_chamar_o_mini(edge):
    edge.fail(GPT_L, "error_500")
    edge.fail(CLA_L, "error_500")   # os dois mini continuam no ar e mesmo assim não são usados
    response, elapsed = edge.post(ROUTE, BODY)

    explicit_app_error(response, 503, "model_unavailable")
    assert "order_number" not in response.json()   # nenhum null artificial
    assert elapsed < SYNC_FAILURE_LIMIT
    models = [c["model"] for c in edge.calls(TASK)]
    assert models == [GPT_L, GPT_L, CLA_L] and not set(models) & MINI


def test_tudo_travado_vira_erro_explicito_da_app_antes_de_15s(edge):
    edge.fail(None, "timeout", provider="openai")
    edge.fail(None, "timeout", provider="anthropic")
    response, elapsed = edge.post(ROUTE, BODY)

    explicit_app_error(response, 503, "model_timeout")
    assert elapsed < SYNC_FAILURE_LIMIT, f"{elapsed:.3f} s"
    assert [c["model"] for c in edge.calls(TASK)] == [GPT_L, CLA_L]
