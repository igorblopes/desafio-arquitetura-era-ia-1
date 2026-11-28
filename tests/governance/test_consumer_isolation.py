"""Isolamento: limite de uma chave não atinge as outras (limites individuais, ADR 0010)."""

from conftest import HELPDESK_KEY, error_type


def test_chave_esgotada_nao_compromete_as_outras(gov):
    budget_key = gov.new_key(max_budget=0.0004)
    rate_key = gov.new_key(max_budget=5.0, rpm_limit=3)
    other_key = gov.new_key(max_budget=5.0, rpm_limit=3)

    gov.exhaust_budget(budget_key)
    gov.exhaust_rpm(rate_key, 3)

    assert error_type(gov.refused_without_provider_call(budget_key)) == "budget_exceeded"
    assert error_type(gov.refused_without_provider_call(rate_key)) == "throttling_error"

    # A chave de orçamento esgotado não está limitada por frequência, e vice-versa.
    assert gov.chat(other_key).status_code == 200
    assert gov.chat(HELPDESK_KEY).status_code == 200
    response = gov.edge.post("/tickets/extraction", json={
        "ticket_id": "TK-00200", "text": "Pedido #481516, o fone de ouvido bluetooth veio com chiado"})
    assert response.status_code == 200
    assert response.json()["order_number"] == "#481516"
