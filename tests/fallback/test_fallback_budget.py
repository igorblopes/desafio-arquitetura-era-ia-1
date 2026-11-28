"""Orçamento temporal, limites por destino e forma da cadeia (ADR 0006).

Parte estática (sem Docker): lê gateway/config.yaml e app/helpdesk/config.py e prova que a
configuração não pode violar as decisões de produto nem o deadline. Parte dinâmica: timeout
e lentidão reais pela borda.
"""

import ast
import pathlib
import re

import pytest
import yaml

from conftest import CLA_L, CLA_M, GPT_L, FEATURES, chain

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATEWAY = yaml.safe_load((ROOT / "gateway" / "config.yaml").read_text(encoding="utf-8"))
ROUTER = GATEWAY["router_settings"]
POLICIES = ROUTER["model_group_retry_policy"]
EDGE_TIMEOUT = 30
JITTER = 0.75
PAUSES_WITH_ONE_RETRY = (0.5 + JITTER) + (1.0 + JITTER)  # antes da retentativa e depois da última
MARGIN = 1.0
# Latência normal medida pela borda (Passo 10/11), por chamada ao modelo.
NORMAL = {"ticket-classification": 1.2, "order-extraction": 1.3, "reply-suggestion": 16.2,
          "topics-report": 9.9}
CAPABILITY_OF = {"F1": "ticket-classification", "F2": "reply-suggestion",
                 "F3": "topics-report", "F4": "order-extraction"}
APPROVED_MINI = {"ticket-classification", "reply-suggestion"}  # decisão de produto


def _app_deadlines() -> dict:
    tree = ast.parse((ROOT / "app" / "helpdesk" / "config.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "GATEWAY_DEADLINE_SECONDS":
            return ast.literal_eval(node.value)
    raise AssertionError("GATEWAY_DEADLINE_SECONDS não encontrado")


DEADLINES = _app_deadlines()
GROUPS: dict[str, list[dict]] = {}
for entry in GATEWAY["model_list"]:
    GROUPS.setdefault(entry["model_name"], []).append(entry["litellm_params"])
FALLBACKS = {k: v for item in ROUTER["fallbacks"] for k, v in item.items()}


def _params(group: str) -> dict:
    return GROUPS[group][0]


def _physical(group: str) -> str:
    return _params(group)["model"].split("/", 1)[1]


def _provider(group: str) -> str:
    return _params(group)["model"].split("/", 1)[0]


def _worst_case(group: str) -> float:
    """Pior tempo num destino: falha imediata retentada e a retentativa travando até o timeout."""
    timeout = _params(group)["timeout"]
    policy = POLICIES[group]
    if policy.get("InternalServerErrorRetries", 0) >= 1:
        return max(timeout * (1 + policy["TimeoutErrorRetries"]), PAUSES_WITH_ONE_RETRY + timeout)
    return timeout * (1 + policy["TimeoutErrorRetries"])


# ---------------- forma da cadeia ----------------

def test_every_app_capability_has_a_chain_and_nothing_else_does():
    assert set(FALLBACKS) == set(DEADLINES)


@pytest.mark.parametrize("capability", sorted(DEADLINES))
def test_chain_order_large_then_equivalent_large_of_other_provider_then_approved_mini(capability):
    targets = FALLBACKS[capability]
    assert _physical(capability).endswith("-large")
    equivalent = targets[0]
    assert _physical(equivalent).endswith("-large")
    assert _provider(equivalent) != _provider(capability)
    if capability in APPROVED_MINI:
        assert len(targets) == 2 and _physical(targets[1]).endswith("-mini")
    else:
        assert len(targets) == 1  # nenhuma configuração pode levar F3/F4 a um mini


def test_chains_are_finite_and_acyclic():
    targets = [t for chain_ in FALLBACKS.values() for t in chain_]
    assert len(targets) == len(set(targets))  # cada destino interno pertence a uma só cadeia
    assert not set(targets) & set(FALLBACKS)  # destino de fallback não tem fallback próprio
    assert ROUTER["max_fallbacks"] == max(len(c) for c in FALLBACKS.values())


def test_one_deployment_per_group_so_the_primary_is_never_drawn_at_random():
    assert all(len(deployments) == 1 for deployments in GROUPS.values())


def test_attempt_limits_per_destination():
    for capability, targets in FALLBACKS.items():
        primary = POLICIES[capability]
        assert primary["InternalServerErrorRetries"] == primary["ServiceUnavailableErrorRetries"] == 1
        assert primary["TimeoutErrorRetries"] == primary["RateLimitErrorRetries"] == 0
        assert primary["BadRequestErrorRetries"] == primary["AuthenticationErrorRetries"] == 0
        for target in targets:
            assert set(POLICIES[target].values()) == {0}  # uma tentativa, qualquer erro
    # máximo de chamadas por operação de modelo = 2 + 1 (+ 1 se houver mini)
    assert {c: 2 + len(t) for c, t in FALLBACKS.items()} == {
        "ticket-classification": 4, "reply-suggestion": 4, "topics-report": 3, "order-extraction": 3}


def test_app_knows_neither_physical_models_nor_internal_destinations():
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").rglob("*.py"))
    assert not re.search(r"gpt-fake|claude-fake|-equivalent|-degraded", source)


# ---------------- orçamento ----------------

@pytest.mark.parametrize("capability", ["ticket-classification", "order-extraction"])
def test_short_capabilities_fit_the_whole_chain_in_the_deadline(capability):
    worst = _worst_case(capability) + sum(_worst_case(t) for t in FALLBACKS[capability])
    assert worst + MARGIN <= DEADLINES[capability] < 15  # F1: sucesso ou erro em até 15 s


@pytest.mark.parametrize("capability", ["reply-suggestion", "topics-report"])
def test_long_capabilities_fit_fast_failure_recovery_in_the_deadline(capability):
    equivalent = FALLBACKS[capability][0]
    fast_failure = PAUSES_WITH_ONE_RETRY + NORMAL[capability]  # 500, 500 e o equivalente responde
    assert fast_failure + MARGIN <= DEADLINES[capability] < EDGE_TIMEOUT
    hung_primary = _params(capability)["timeout"] + NORMAL[capability]
    if capability == "topics-report":
        assert hung_primary + MARGIN <= DEADLINES[capability]  # lote recuperável após travar
    else:
        # Limitação aceita (ADR 0006): a F2 síncrona não tem tempo para o equivalente depois
        # de um primário travado. Resolve-se com streaming (Passo 14), não com prazo maior.
        assert hung_primary > EDGE_TIMEOUT
    assert _params(equivalent)["timeout"] == _params(capability)["timeout"]


# ---------------- dinâmico ----------------

def test_f1_hung_primary_recovers_on_the_equivalent_well_within_15s(stack):
    stack.fail(GPT_L, "timeout")

    response, seconds = stack.run("F1")

    assert response.status_code == 200
    assert response.json() == FEATURES["F1"][4]
    assert [(c["model"], c["status"]) for c in stack.calls("F1")] == [(GPT_L, 504), (CLA_L, 200)]
    assert 3.0 <= seconds <= 5.5


def test_f1_slow_primary_is_cut_by_its_timeout_and_recovered(stack):
    stack.fail(GPT_L, "slow")

    response, seconds = stack.run("F1")

    assert response.status_code == 200
    assert [c["model"] for c in stack.calls("F1")] == [GPT_L, CLA_L]
    assert seconds <= 5.5


def test_f3_hung_primary_recovers_the_batch_inside_its_deadline(stack):
    stack.fail(CLA_L, "timeout")

    response, seconds = stack.run("F3")

    assert response.status_code == 200
    assert response.json() == FEATURES["F3"][4]
    assert [(c["model"], c["status"]) for c in stack.calls("F3")] == [(CLA_L, 504), (GPT_L, 200)]
    assert seconds < DEADLINES["topics-report"]


def test_f2_hung_primary_hits_the_deadline_and_the_orphan_chain_stays_finite(stack):
    stack.fail(CLA_L, "timeout")
    stack.fail(GPT_L, "timeout")
    stack.fail(CLA_M, "timeout")

    response, seconds = stack.run("F2")

    assert response.status_code == 503
    assert response.json()["code"] == "model_timeout"  # da app, antes dos 30 s da borda
    assert DEADLINES["reply-suggestion"] <= seconds < EDGE_TIMEOUT
    # A app desistiu, mas o gateway segue a cadeia sozinho (sem deadline por requisição).
    stack.wait_chain_end("F2", expected_calls=3, limit=30)
    assert [c["model"] for c in stack.calls("F2")] == chain("F2")  # termina no mini, sem ciclo
