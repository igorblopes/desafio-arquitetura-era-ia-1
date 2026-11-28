"""Orçamento de latência, sem Docker: a configuração precisa caber nos prazos (ADR 0005)."""

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


CAPABILITIES = {m["model_name"]: m["litellm_params"] for m in GATEWAY["model_list"]}
POLICIES = GATEWAY["router_settings"]["model_group_retry_policy"]


def test_every_capability_has_explicit_timeout_retry_policy_and_deadline():
    assert set(CAPABILITIES) == set(POLICIES) == set(_app_deadlines())
    assert all(params["timeout"] > 0 for params in CAPABILITIES.values())
    assert GATEWAY["router_settings"]["num_retries"] == 1
    assert all(max(policy.values()) <= 1 for policy in POLICIES.values())


@pytest.mark.parametrize("capability", list(CAPABILITIES))
def test_deadline_covers_the_gateway_worst_case_and_stays_below_the_edge(capability):
    timeout = CAPABILITIES[capability]["timeout"]
    if POLICIES[capability]["TimeoutErrorRetries"]:
        # Pausas do LiteLLM 1.102.1: uma antes da retentativa e outra depois da última.
        worst_timeouts = 2 * timeout + (0.5 + JITTER) + (1.0 + JITTER)
    else:
        worst_timeouts = timeout
    worst_429 = 2 * (RETRY_AFTER + JITTER)  # recusas imediatas
    deadline = _app_deadlines()[capability]

    assert max(worst_timeouts, worst_429) < deadline < EDGE_TIMEOUT
    if capability != "reply-suggestion":  # a F2 síncrona leva ~16 s; ver ADR 0005
        assert deadline < 15
