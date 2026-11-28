"""Autenticação e autorização no gateway: quem pode consumir e o quê (ADR 0010)."""

from conftest import F1, HELPDESK_KEY, error_type


def test_chave_do_helpdesk_consome_as_capacidades(gov):
    response = gov.chat(HELPDESK_KEY)
    assert response.status_code == 200
    assert response.headers["x-litellm-model-group"] == F1
    assert gov.count() == 1


def test_helpdesk_pela_borda_usa_a_chave_virtual(gov):
    response = gov.edge.post("/tickets/classification", json={"ticket_id": "TK-00042",
                                                              "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"})
    assert response.status_code == 200
    assert response.json()["category"] == "delivery"


def test_chave_invalida_recusada_antes_do_provider(gov):
    response = gov.refused_without_provider_call("sk-chave-que-nao-existe-9999")
    assert response.status_code == 401


def test_sem_chave_recusada_antes_do_provider(gov):
    response = gov.refused_without_provider_call(None)
    assert response.status_code == 401


def test_chave_revogada_recusada_antes_do_provider(gov):
    key = gov.new_key()
    assert gov.chat(key).status_code == 200
    gov.delete_key(key)
    response = gov.refused_without_provider_call(key)
    assert response.status_code == 401


def test_capacidade_fora_da_chave_recusada(gov):
    key = gov.new_key(models=[F1])
    response = gov.refused_without_provider_call(key, "order-extraction")
    assert response.status_code == 403
    assert error_type(response) == "key_model_access_denied"


def test_helpdesk_nao_chama_grupo_interno_de_fallback(gov):
    # Os grupos -equivalent/-degraded são destinos internos da cadeia (ADR 0006).
    for internal in ("ticket-classification-degraded", "reply-suggestion-equivalent"):
        response = gov.refused_without_provider_call(HELPDESK_KEY, internal)
        assert response.status_code == 403


def test_recusa_nao_ecoa_a_chave_recebida(gov):
    secret = "sk-chave-que-nao-existe-1234567890"
    response = gov.refused_without_provider_call(secret)
    assert secret not in response.text
