"""F4: extração de dados do pedido (POST /tickets/extraction).

Caracteriza o comportamento ATUAL, inclusive os casos discutíveis: o teste
protege contra mudança, não afirma que a resposta é a correta.
"""

import pytest

URL = "/tickets/extraction"

SUCESSO = [
    pytest.param("TK-00042", "Meu pedido #481516 não chegou e já passou do prazo, urgente",
                 "#481516", None, id="pedido-sem-produto"),
    pytest.param("TK-00200", "Pedido #481516, o fone de ouvido bluetooth veio com chiado",
                 "#481516", "fone de ouvido bluetooth", id="pedido-e-produto"),
    pytest.param("TK-00201", "O protocolo #12345 não resolveu, o aspirador robô continua sem funcionar",
                 None, "aspirador robô", id="protocolo-nao-e-pedido"),
    pytest.param("TK-00202", "Como faço para alterar meu e-mail de cadastro?",
                 None, None, id="sem-dados-de-pedido"),
    # Comportamento atual: o número sem '#' é normalizado para '#481516'.
    pytest.param("TK-00203", "Meu pedido 481516 não chegou",
                 "#481516", None, id="numero-sem-cerquilha"),
    pytest.param("TK-00204", "O pedido #4815162 veio com o produto errado",
                 None, None, id="sete-digitos-nao-e-pedido"),
    # Comportamento atual (provavelmente incorreto): pega o primeiro pedido,
    # embora o produto com defeito seja o do segundo (#445566).
    pytest.param("TK-00205",
                 "Comprei a air fryer no pedido #112233 e a cafeteira elétrica no pedido #445566; "
                 "só a cafeteira veio quebrada",
                 "#112233", "cafeteira elétrica", id="dois-pedidos-pega-o-primeiro"),
]


@pytest.mark.parametrize("ticket_id, text, order_number, product", SUCESSO)
def test_extrai_dados_do_pedido(client, ticket_id, text, order_number, product):
    # Arrange
    payload = {"ticket_id": ticket_id, "text": text}

    # Act
    resp = client.post(URL, json=payload)

    # Assert
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ticket_id": ticket_id, "order_number": order_number, "product": product}


@pytest.mark.parametrize("payload, detail", [
    pytest.param({"text": "x"}, {"detail": [
        {"type": "missing", "loc": ["body", "ticket_id"], "msg": "Field required",
         "input": {"text": "x"}},
    ]}, id="sem-ticket-id"),
    pytest.param({"ticket_id": "TK-1", "text": ""}, {"detail": [
        {"type": "string_too_short", "loc": ["body", "text"],
         "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}},
    ]}, id="texto-vazio"),
])
def test_rejeita_entrada_invalida(client, payload, detail):
    resp = client.post(URL, json=payload)

    assert resp.status_code == 422
    assert resp.json() == detail
