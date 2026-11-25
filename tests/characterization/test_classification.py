"""F1: classificação de ticket (POST /tickets/classification).

Valores esperados copiados de respostas reais observadas pela borda em
25/11/2026 com o provider-fake em modo normal. Não são calculados.
"""

import pytest

URL = "/tickets/classification"

SUCESSO = [
    pytest.param("TK-00042", "Meu pedido #481516 não chegou e já passou do prazo, urgente",
                 "delivery", "high", id="entrega-urgente"),
    pytest.param("TK-00100", "Fui cobrado duas vezes no cartão pela mesma compra",
                 "payment", "high", id="cobranca-duplicada"),
    pytest.param("TK-00101", "Quero trocar a camiseta básica por um tamanho maior, sem pressa",
                 "exchange_return", "medium", id="troca-sem-pressa"),
    pytest.param("TK-00102", "O liquidificador chegou quebrado e não liga",
                 "product_defect", "medium", id="produto-quebrado"),
    pytest.param("TK-00103", "Como faço para alterar meu e-mail de cadastro?",
                 "other", "medium", id="duvida-cadastro"),
    # Comportamento atual: a palavra "urgente" pesa mais que a negação.
    pytest.param("TK-00104", "Não é urgente, só queria saber se vocês têm loja física",
                 "other", "high", id="negacao-de-urgencia-vira-high"),
    pytest.param("TK-00105", "Quando puder, me informe o prazo de entrega, sem pressa nenhuma",
                 "delivery", "medium", id="prazo-de-entrega"),
    # Único caso observado com prioridade low.
    pytest.param("TK-00106", "Dúvida simples: posso pagar com dois cartões?",
                 "other", "low", id="duvida-simples-low"),
    pytest.param("TK-00107", "Obrigado, o problema já foi resolvido, podem fechar o chamado",
                 "other", "medium", id="agradecimento"),
]


@pytest.mark.parametrize("ticket_id, text, category, priority", SUCESSO)
def test_classifica_ticket(client, ticket_id, text, category, priority):
    # Arrange
    payload = {"ticket_id": ticket_id, "text": text}

    # Act
    resp = client.post(URL, json=payload)

    # Assert
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ticket_id": ticket_id, "category": category, "priority": priority}


ERROS = [
    pytest.param({}, {"detail": [
        {"type": "missing", "loc": ["body", "ticket_id"], "msg": "Field required", "input": {}},
        {"type": "missing", "loc": ["body", "text"], "msg": "Field required", "input": {}},
    ]}, id="corpo-vazio"),
    pytest.param({"ticket_id": "", "text": "x"}, {"detail": [
        {"type": "string_too_short", "loc": ["body", "ticket_id"],
         "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}},
    ]}, id="ticket-id-vazio"),
    pytest.param({"ticket_id": "TK-1", "text": ""}, {"detail": [
        {"type": "string_too_short", "loc": ["body", "text"],
         "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}},
    ]}, id="texto-vazio"),
    pytest.param({"ticket_id": "TK-1", "text": 123}, {"detail": [
        {"type": "string_type", "loc": ["body", "text"],
         "msg": "Input should be a valid string", "input": 123},
    ]}, id="texto-nao-string"),
]


@pytest.mark.parametrize("payload, detail", ERROS)
def test_rejeita_entrada_invalida(client, payload, detail):
    resp = client.post(URL, json=payload)

    assert resp.status_code == 422
    assert resp.json() == detail
