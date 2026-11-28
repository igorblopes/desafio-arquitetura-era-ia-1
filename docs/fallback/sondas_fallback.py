"""Sondas do Passo 11: cada feature pela borda com falhas injetadas em destinos do gateway.

Para cada feature: POST /admin/reset, liga as falhas do cenário, chama a borda como um
cliente real, espera as chamadas abertas terminarem (ou o limite de --espera) e lê
/admin/calls ANTES de resetar de novo. Registra status, corpo, tempo, cada chamada ao
provider (provider, modelo, status, duração, tokens), custo estimado e chamadas ainda
abertas. No fim o provider volta ao modo normal, mesmo com erro. Só biblioteca padrão.

Uso (raiz do repositório, compose no ar):

    python docs/fallback/sondas_fallback.py CENARIO [F1 F2 F3 F4] [--espera 5] [--saida arq.json]

CENARIO: um dos nomes de CENARIOS abaixo (normal, primario-500, larges-500, ...).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

EDGE = "http://localhost:8000"
PROVIDER = "http://localhost:8090"

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"

# Os nomes físicos aparecem aqui, e não na app, só para a sonda saber onde injetar a falha.
GPT_L, CLA_L, GPT_M, CLA_M = "gpt-fake-large", "claude-fake-large", "gpt-fake-mini", "claude-fake-mini"
PROVIDER_OF = {GPT_L: "openai", GPT_M: "openai", CLA_L: "anthropic", CLA_M: "anthropic"}
FEATURES = {
    "F1": ("/tickets/classification", {"ticket_id": "TK-00042", "text": T42}, GPT_L),
    "F2": ("/tickets/reply-suggestion", {"ticket_id": "TK-00042", "text": T42}, CLA_L),
    "F3": ("/reports/topics", {"start": "2026-08-01", "end": "2026-08-01"}, CLA_L),
    "F4": ("/tickets/extraction", {"ticket_id": "TK-00200", "text": T200}, GPT_L),
}
# Tarefa que cada feature envia; chamada com outra tarefa no registro é resto de um
# experimento anterior (cadeia órfã ainda andando no gateway) e aparece marcada.
TASKS = {"F1": "classify", "F2": "suggest", "F3": "topics", "F4": "extract"}
PRICES = {GPT_L: (2.50, 10.00), CLA_L: (3.00, 15.00), GPT_M: (0.15, 0.60), CLA_M: (0.80, 4.00)}


def _primary(feature: str) -> list[tuple[str, str | None, str]]:
    model = FEATURES[feature][2]
    return [(PROVIDER_OF[model], model, "{mode}")]


# cenário -> função(feature) que devolve a lista de falhas (provider, modelo ou None, modo)
CENARIOS = {
    "normal": lambda f: [],
    "primario-500": lambda f: [(p, m, "error_500") for p, m, _ in _primary(f)],
    "primario-429": lambda f: [(p, m, "error_429") for p, m, _ in _primary(f)],
    "primario-timeout": lambda f: [(p, m, "timeout") for p, m, _ in _primary(f)],
    "primario-slow": lambda f: [(p, m, "slow") for p, m, _ in _primary(f)],
    "larges-500": lambda f: [("openai", GPT_L, "error_500"), ("anthropic", CLA_L, "error_500")],
    "providers-500": lambda f: [("openai", None, "error_500"), ("anthropic", None, "error_500")],
    "providers-timeout": lambda f: [("openai", None, "timeout"), ("anthropic", None, "timeout")],
}


def _request(method: str, url: str, body: dict | None = None, timeout: float = 60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def calls() -> list[dict]:
    _, text = _request("GET", f"{PROVIDER}/admin/calls?last=200")
    body = json.loads(text)
    body = body["calls"] if isinstance(body, dict) else body
    return sorted(body, key=lambda c: c["ts"])


def cost(call: dict) -> float | None:
    if call["output_tokens"] is None:
        return None
    price_in, price_out = PRICES[call["model"]]
    return (call["input_tokens"] * price_in + call["output_tokens"] * price_out) / 1_000_000


def run(feature: str, cenario: str, espera: float) -> dict:
    route, body, _ = FEATURES[feature]
    _request("POST", f"{PROVIDER}/admin/reset")
    failures = CENARIOS[cenario](feature)
    for provider, model, mode in failures:
        payload = {"provider": provider, "mode": mode}
        if model:
            payload["model"] = model
        _request("POST", f"{PROVIDER}/admin/failures", payload)
    start = time.monotonic()
    status, text = _request("POST", f"{EDGE}{route}", body, timeout=60)
    seconds = time.monotonic() - start
    limit = time.monotonic() + espera
    while any(c["duration_ms"] is None for c in calls()) and time.monotonic() < limit:
        time.sleep(0.2)
    registered = calls()
    _request("POST", f"{PROVIDER}/admin/reset")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text[:300]
    if isinstance(parsed, dict) and "suggestion" in parsed:
        parsed = {**parsed, "suggestion": f"<{len(parsed['suggestion'])} caracteres>"}
    if isinstance(parsed, dict) and "topics" in parsed:
        parsed = {**parsed, "topics": f"<{len(parsed['topics'])} temas, soma "
                                      f"{sum(t['count'] for t in parsed['topics'])}>"}
    custos = [cost(c) for c in registered]
    return {
        "feature": feature,
        "cenario": cenario,
        "falhas": [{"provider": p, "model": m, "mode": mode} for p, m, mode in failures],
        "http": status,
        "segundos": round(seconds, 3),
        "corpo": parsed,
        "chamadas": [{k: c.get(k) for k in ("ts", "provider", "model", "task", "status", "duration_ms",
                                             "input_tokens", "output_tokens")} for c in registered],
        "sequencia": [f"{c['model']}:{c['status']}" + ("" if c.get("task") == TASKS[feature]
                                                         else f"[{c.get('task')}]") for c in registered],
        "abertas_apos_espera": sum(1 for c in registered if c["duration_ms"] is None),
        "custo_concluidas_usd": round(sum(x for x in custos if x is not None), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cenario", choices=sorted(CENARIOS))
    parser.add_argument("features", nargs="*", default=["F1", "F4", "F2", "F3"])
    parser.add_argument("--espera", type=float, default=5.0,
                        help="segundos para esperar chamadas ainda abertas no provider")
    parser.add_argument("--saida")
    args = parser.parse_args()
    results = []
    try:
        for feature in args.features:
            result = run(feature, args.cenario, args.espera)
            results.append(result)
            print(f"{args.cenario:18} {feature}  HTTP {result['http']}  {result['segundos']:7.3f}s  "
                  f"{' -> '.join(result['sequencia'])}  abertas={result['abertas_apos_espera']}  "
                  f"US$ {result['custo_concluidas_usd']}", flush=True)
    finally:
        _request("POST", f"{PROVIDER}/admin/reset")
    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as file:
            json.dump(results, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())
