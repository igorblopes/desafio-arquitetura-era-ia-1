"""Orçamento de latência de UM destino, sem Docker (ADR 0005, revisado no ADR 0006).

A conta da cadeia inteira (primário + equivalente + mini) está em
tests/fallback/test_fallback_budget.py.
"""

import ast
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATEWAY = yaml.safe_load((ROOT / "gateway" / "config.yaml").read_text(encoding="utf-8"))
EDGE_TIMEOUT = 30
JITTER = 0.75
RETRY_AFTER = 2  # valor que o provider-fake envia


def _app_deadlines() -> dict:
    tree = ast.parse((ROOT / "app" / "helpdesk" / "config.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "GATEWAY_DEADLINE_SECONDS":
            return ast.literal_eval(node.value)
    raise AssertionError("GATEWAY_DEADLINE_SECONDS não encontrado")


DEADLINES = _app_deadlines()
# Só os destinos primários: as capacidades lógicas que a app pede.
CAPABILITIES = {m["model_name"]: m["litellm_params"] for m in GATEWAY["model_list"]
                if m["model_name"] in DEADLINES}
POLICIES = GATEWAY["router_settings"]["model_group_retry_policy"]


def test_every_capability_has_explicit_timeout_retry_policy_and_deadline():
    assert set(CAPABILITIES) == set(DEADLINES) <= set(POLICIES)
    assert all(params["timeout"] > 0 for params in CAPABILITIES.values())
    assert GATEWAY["router_settings"]["num_retries"] == 1
    assert all(max(policy.values()) <= 1 for policy in POLICIES.values())


@pytest.mark.parametrize("capability", list(CAPABILITIES))
def test_deadline_covers_the_gateway_worst_case_and_stays_below_the_edge(capability):
    timeout = CAPABILITIES[capability]["timeout"]
    pauses = (0.5 + JITTER) + (1.0 + JITTER)  # LiteLLM 1.102.1: antes da retentativa e depois da última
    policy = POLICIES[capability]
    worst_timeouts = 2 * timeout + pauses if policy["TimeoutErrorRetries"] else timeout
    worst_500_then_hang = pauses + timeout if policy["InternalServerErrorRetries"] else timeout
    worst_429 = 2 * (RETRY_AFTER + JITTER) if policy["RateLimitErrorRetries"] else 0
    deadline = DEADLINES[capability]

    assert max(worst_timeouts, worst_500_then_hang, worst_429) < deadline < EDGE_TIMEOUT
    if capability in ("ticket-classification", "order-extraction"):
        # F1: 15 s é requisito. F2 (~16 s normal) e F3 por lote (25 s para caber o fallback
        # depois de um primário travado) ficam abaixo só da borda: ADR 0005 e ADR 0006.
        assert deadline < 15
