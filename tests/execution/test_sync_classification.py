"""F1 síncrona pela borda: contrato, 3 s em modo normal e resposta limitada sob falha.

Não repete os valores caracterizados um a um (isso é tests/characterization): aqui a
pergunta é se o MODO síncrono cumpre o que o enunciado exige da F1, com o tempo medido como
o cliente vê (http://localhost:8000) e as chamadas comprovadas em /admin/calls.
"""

import pytest

from conftest import (CATEGORIES, CLA_L, F1_NORMAL_LIMIT, GPT_L, GPT_M, PRIORITIES,
                      SYNC_FAILURE_LIMIT, T42, explicit_app_error)

ROUTE = "/tickets/classification"
TASK = "classify"
BODY = {"ticket_id": "TK-00042", "text": T42}
EXPECTED = {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}

# Mesmas entradas da caracterização, com o resultado caracterizado.
INPUTS = [
    ("TK-00042", T42, "delivery", "high"),
    ("TK-00100", "Fui cobrado duas vezes no cartão pela mesma compra", "payment", "high"),
    ("TK-00101", "Quero trocar a camiseta básica por um tamanho maior, sem pressa", "exchange_return", "medium"),
    ("TK-00102", "O liquidificador chegou quebrado e não liga", "product_defect", "medium"),
    ("TK-00103", "Como faço para alterar meu e-mail de cadastro?", "other", "medium"),
    ("TK-00104", "Não é urgente, só queria saber se vocês têm loja física", "other", "high"),
    ("TK-00105", "Quando puder, me informe o prazo de entrega, sem pressa nenhuma", "delivery", "medium"),
    ("TK-00106", "Dúvida simples: posso pagar com dois cartões?", "other", "low"),
    ("TK-00107", "Obrigado, o problema já foi resolvido, podem fechar o chamado", "other", "medium"),
]


@pytest.mark.parametrize("ticket_id, text, category, priority", INPUTS, ids=[i[0] for i in INPUTS])
def test_resultado_completo_em_ate_3s_no_primario(edge, ticket_id, text, category, priority):
    response, elapsed = edge.post(ROUTE, {"ticket_id": ticket_id, "text": text})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"ticket_id", "category", "priority"}
    assert body["category"] in CATEGORIES and body["priority"] in PRIORITIES
    assert body == {"ticket_id": ticket_id, "category": category, "priority": priority}
    assert elapsed <= F1_NORMAL_LIMIT, f"{elapsed:.3f} s"
    # Uma única chamada, no primário: nada de tentativa desnecessária.
    assert [(c["model"], c["status"]) for c in edge.calls(TASK)] == [(GPT_L, 200)]


def test_entrada_invalida_nao_chama_o_modelo(edge):
    response, _ = edge.post(ROUTE, {"ticket_id": "TK-1"})
    assert response.status_code == 422
    assert edge.calls(TASK) == []


def test_primario_500_recupera_pelo_large_equivalente(edge):
    edge.fail(GPT_L, "error_500")
    response, elapsed = edge.post(ROUTE, BODY)

    assert response.status_code == 200 and response.json() == EXPECTED
    assert elapsed < SYNC_FAILURE_LIMIT
    # 2 tentativas no primário (500 repete 1 vez), depois o large do OUTRO provider.
    assert [(c["model"], c["status"]) for c in edge.calls(TASK)] == [(GPT_L, 500), (GPT_L, 500), (CLA_L, 200)]


def test_primario_travado_responde_pelo_fallback_em_menos_de_15s(edge):
    edge.fail(GPT_L, "timeout")
    response, elapsed = edge.post(ROUTE, BODY)

    assert response.status_code == 200 and response.json() == EXPECTED
    assert elapsed < SYNC_FAILURE_LIMIT, f"{elapsed:.3f} s"
    # Timeout não repete no mesmo destino: migra direto.
    assert [c["model"] for c in edge.calls(TASK)] == [GPT_L, CLA_L]


def test_tudo_travado_vira_erro_explicito_da_app_antes_de_15s(edge):
    edge.fail(None, "timeout", provider="openai")
    edge.fail(None, "timeout", provider="anthropic")
    response, elapsed = edge.post(ROUTE, BODY)

    explicit_app_error(response, 503, "model_timeout")   # não é o 504 HTML da borda
    assert elapsed < SYNC_FAILURE_LIMIT, f"{elapsed:.3f} s"
    # Cadeia finita: primário, equivalente e o mini aprovado para a F1, uma vez cada.
    assert [c["model"] for c in edge.calls(TASK)] == [GPT_L, CLA_L, GPT_M]


def test_indisponibilidade_total_vira_503_sem_resultado_ficticio(edge):
    edge.fail(None, "error_500", provider="openai")
    edge.fail(None, "error_500", provider="anthropic")
    response, elapsed = edge.post(ROUTE, BODY)

    explicit_app_error(response, 503, "model_unavailable")
    assert "category" not in response.json()
    assert elapsed < SYNC_FAILURE_LIMIT
    # Máximo declarado da F1: 2 + 1 + 1 = 4 chamadas, sem ciclo.
    assert [c["model"] for c in edge.calls(TASK)] == [GPT_L, GPT_L, CLA_L, GPT_M]
