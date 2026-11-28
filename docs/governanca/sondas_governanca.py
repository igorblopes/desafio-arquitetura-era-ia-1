"""Sondas do Passo 12: experimentos de governança contra o gateway real e o provider-fake.

Cada experimento grava um JSON em docs/governanca/evidencias/ com status, corpos, headers
de governança do gateway, chamadas em /admin/calls antes e depois e trechos do log do
gateway. A prova de bloqueio é sempre a mesma: contar /admin/calls, fazer a requisição
recusada, contar de novo, SEM /admin/reset no meio.

Uso (raiz do repositório, compose no ar, chaves de demonstração no estado pedido):

    python docs/governanca/sondas_governanca.py EXPERIMENTO [--saida arquivo.json]

EXPERIMENTO: precos, autenticacao, budget, rate, isolamento, fallback-budget,
fallback-rate, custo-cadeia, concorrencia-budget, concorrencia-rate, latencia.

Os experimentos de orçamento exigem a chave de demonstração zerada antes:

    docker compose run --rm gateway-bootstrap --reset-spend governance-budget-demo

Os de rate limit esperam a janela da chave de demonstração ficar livre (até 61 s).
Só biblioteca padrão; os valores das chaves vêm do .env (mascarados na saída).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "governanca" / "evidencias"
EDGE, GATEWAY, PROVIDER = "http://localhost:8000", "http://localhost:4000", "http://localhost:8090"


def _env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


ENV = _env()
MASTER = ENV["GATEWAY_MASTER_KEY"]
HELPDESK = ENV["HELPDESK_GATEWAY_KEY"]
BUDGET = ENV["GOVERNANCE_BUDGET_KEY"]
RATE = ENV["GOVERNANCE_RATE_KEY"]
ALIAS = {MASTER: "master", HELPDESK: "helpdesk-app", BUDGET: "governance-budget-demo",
         RATE: "governance-rate-demo"}

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
PROMPT_F1 = f"TASK: classify\n{T42}"
PRICES = {"gpt-fake-large": (2.50, 10.00), "claude-fake-large": (3.00, 15.00),
          "gpt-fake-mini": (0.15, 0.60), "claude-fake-mini": (0.80, 4.00)}
PROVIDER_OF = {"gpt-fake-large": "openai", "gpt-fake-mini": "openai",
               "claude-fake-large": "anthropic", "claude-fake-mini": "anthropic"}
GOV_HEADERS = ("retry-after", "x-ratelimit-api_key-remaining-requests",
               "x-ratelimit-api_key-limit-requests", "x-litellm-response-cost",
               "x-litellm-model-group", "x-litellm-model-name", "x-litellm-attempted-retries",
               "x-litellm-attempted-fallbacks", "x-litellm-overhead-duration-ms",
               "x-litellm-response-duration-ms")
FLUSH = 16.0  # ciclo de gravação do gasto no banco: 10 s + até 5 s (LiteLLM v1.102.1)


def mask(key: str | None) -> str:
    if key is None:
        return "(sem chave)"
    return f"{ALIAS.get(key, 'outra')} sk-...{key[-4:]}"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def http(method: str, url: str, body: dict | None = None, key: str | None = None,
         timeout: float = 60.0) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw, hdrs = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, raw, hdrs = error.code, error.read(), error.headers
    elapsed = round(time.monotonic() - start, 3)
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = text
    return {"status": status, "body": parsed, "elapsed_s": elapsed,
            "headers": {h: hdrs.get(h) for h in GOV_HEADERS if hdrs.get(h) is not None}}


def chat(key: str | None, capability: str = "ticket-classification", prompt: str = PROMPT_F1) -> dict:
    result = http("POST", f"{GATEWAY}/v1/chat/completions",
                  {"model": capability, "messages": [{"role": "user", "content": prompt}]}, key)
    result.update({"ts": now(), "chave": mask(key), "capacidade": capability})
    if isinstance(result["body"], dict) and "choices" in result["body"]:
        result["body"] = {"content": result["body"]["choices"][0]["message"]["content"],
                          "usage": result["body"].get("usage")}
    return result


def calls() -> list[dict]:
    body = http("GET", f"{PROVIDER}/admin/calls?last=500")["body"]
    body = body["calls"] if isinstance(body, dict) else body
    return sorted(body, key=lambda c: c["ts"])


def provider_reset() -> None:
    http("POST", f"{PROVIDER}/admin/reset")


def fail(model: str | None, mode: str, provider: str | None = None) -> None:
    body = {"provider": provider or PROVIDER_OF[model], "mode": mode}
    if model:
        body["model"] = model
    http("POST", f"{PROVIDER}/admin/failures", body)


def key_info(key: str) -> dict:
    info = http("GET", f"{GATEWAY}/key/info?key={key}", key=MASTER)["body"]["info"]
    return {k: info.get(k) for k in ("key_alias", "models", "max_budget", "budget_duration",
                                     "rpm_limit", "spend", "budget_reset_at")}


def gateway_log(since: str, pattern: str) -> list[str]:
    try:
        out = subprocess.run(["docker", "compose", "logs", "gateway", "--no-log-prefix",
                              "--since", since], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"(log indisponível: {error})"]
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in out.splitlines()]
    return [line[:300] for line in lines if re.search(pattern, line, re.I)][-8:]


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES[model]
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def proof(key: str | None, capability: str = "ticket-classification",
          log_pattern: str = r"429|401|budget|rate limit|authentication") -> dict:
    """Prova de bloqueio: /admin/calls antes, requisição, /admin/calls depois (sem reset)."""
    since = now()
    before = len(calls())
    response = chat(key, capability)
    time.sleep(1.0)  # margem para uma chamada que tivesse sido encaminhada aparecer no registro
    after = len(calls())
    return {"chamadas_antes": before, "resposta": response, "chamadas_depois": after,
            "novas_chamadas_ao_provider": after - before,
            "log_gateway": gateway_log(since, log_pattern)}


def wait_window(seconds: float = 61.0) -> None:
    print(f"  aguardando {seconds:.0f} s para a janela de rate limit da chave ficar livre...",
          flush=True)
    time.sleep(seconds)


# ------------------------------------------------------------------- experimentos


def exp_precos() -> dict:
    """Um chamado curto em cada modelo físico, pela master key (validação administrativa)."""
    provider_reset()
    groups = {"ticket-classification": "gpt-fake-large", "reply-suggestion": "claude-fake-large",
              "ticket-classification-degraded": "gpt-fake-mini",
              "reply-suggestion-degraded": "claude-fake-mini"}
    rows = []
    for group, model in groups.items():
        response = chat(MASTER, group)
        call = calls()[-1]
        expected = cost(call["model"], call["input_tokens"], call["output_tokens"])
        registered = float(response["headers"].get("x-litellm-response-cost", "nan"))
        rows.append({"grupo": group, "modelo_esperado": model, "modelo_chamado": call["model"],
                     "tokens_entrada": call["input_tokens"], "tokens_saida": call["output_tokens"],
                     "preco_por_1M": PRICES[model], "custo_manual": round(expected, 10),
                     "custo_registrado": registered,
                     "confere": abs(expected - registered) < 1e-12 and call["model"] == model})
    return {"linhas": rows}


def exp_autenticacao() -> dict:
    provider_reset()
    scenarios = {}
    scenarios["chave_valida"] = proof(HELPDESK)
    scenarios["chave_invalida"] = proof("sk-chave-que-nao-existe-9999")
    scenarios["sem_chave"] = proof(None)
    scenarios["capacidade_nao_autorizada"] = proof(BUDGET, "order-extraction")
    scenarios["grupo_interno_direto"] = proof(HELPDESK, "ticket-classification-degraded")
    # Revogação: chave temporária criada, usada, apagada e usada de novo.
    temp = "sk-governance-revoke-demo-0001"
    http("POST", f"{GATEWAY}/key/delete", {"keys": [temp]}, MASTER)
    created = http("POST", f"{GATEWAY}/key/generate",
                   {"key": temp, "key_alias": "governance-revoke-demo",
                    "models": ["ticket-classification"], "max_budget": 0.01}, MASTER)
    ALIAS[temp] = "governance-revoke-demo"
    scenarios["revogada_antes"] = proof(temp)
    deleted = http("POST", f"{GATEWAY}/key/delete", {"keys": [temp]}, MASTER)
    scenarios["revogada_depois"] = proof(temp)
    scenarios["revogacao"] = {"criada": created["status"], "apagada": deleted["status"]}
    return scenarios


def exp_budget(maximo: int = 6) -> dict:
    """Chamadas da F1 com a chave de orçamento até a primeira recusa (no máximo `maximo`)."""
    provider_reset()
    info0 = key_info(BUDGET)
    if info0["spend"] != 0:
        sys.exit("zere antes: docker compose run --rm gateway-bootstrap --reset-spend governance-budget-demo")
    rows, accumulated = [], 0.0
    for n in range(1, maximo + 1):
        before = len(calls())
        response = chat(BUDGET)
        time.sleep(0.5)
        new = calls()[before:]
        call_cost = sum(cost(c["model"], c["input_tokens"], c["output_tokens"] or 0) for c in new)
        accumulated += call_cost
        rows.append({"n": n, "status": response["status"],
                     "modelo": [c["model"] for c in new],
                     "tokens": [(c["input_tokens"], c["output_tokens"]) for c in new],
                     "custo_manual": round(call_cost, 10),
                     "custo_registrado": response["headers"].get("x-litellm-response-cost"),
                     "acumulado_manual": round(accumulated, 10),
                     "disponivel_manual": round(info0["max_budget"] - accumulated, 10),
                     "chegou_ao_provider": len(new) > 0, "corpo": response["body"]
                     if response["status"] != 200 else None})
        if response["status"] != 200:
            break
    block = proof(BUDGET, log_pattern=r"budget")
    time.sleep(FLUSH)
    return {"antes": info0, "requisicoes": rows, "prova_bloqueio": block,
            "depois_gravacao": key_info(BUDGET)}


def exp_rate(espera: bool = True) -> dict:
    provider_reset()
    if espera:
        wait_window()
    info = key_info(RATE)
    rows = []
    for n in range(1, info["rpm_limit"] + 1):
        before = len(calls())
        response = chat(RATE)
        time.sleep(0.3)
        rows.append({"n": n, "horario": response["ts"], "status": response["status"],
                     "headers": response["headers"], "chegou_ao_provider": len(calls()) > before})
    block = proof(RATE, log_pattern=r"rate limit|429")
    # Recusas contam na janela? Mais duas recusas e depois espera o horário anunciado.
    extra = [chat(RATE)["status"] for _ in range(2)]
    message = block["resposta"]["body"]["error"]["message"] if isinstance(block["resposta"]["body"], dict) else ""
    match = re.search(r"resets at: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", message)
    recovery = None
    if match:
        reset_at = dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        wait = (reset_at - dt.datetime.now(dt.timezone.utc)).total_seconds()
        just_before = None
        if wait > 3:
            time.sleep(wait - 3)
            just_before = chat(RATE)["status"]  # 3 s antes do fim da janela: ainda recusada?
            time.sleep(4)
        else:
            time.sleep(max(wait, 0) + 1)
        before = len(calls())
        after_window = chat(RATE)
        time.sleep(0.5)
        recovery = {"janela_termina": reset_at.isoformat(), "status_3s_antes": just_before,
                    "status_apos": after_window["status"], "horario_apos": after_window["ts"],
                    "headers_apos": after_window["headers"],
                    "chegou_ao_provider": len(calls()) > before}
    return {"politica": info, "requisicoes": rows, "prova_bloqueio": block,
            "recusas_extras": extra, "recuperacao": recovery}


def exp_isolamento() -> dict:
    """Pré-condição: chave de orçamento já esgotada (rode `budget` antes)."""
    provider_reset()
    wait_window()
    rate = [chat(RATE)["status"] for _ in range(3)]
    result = {"rate_esgotando_janela": rate}
    result["governance-rate-demo"] = proof(RATE)
    result["governance-budget-demo"] = proof(BUDGET)
    before = len(calls())
    edge = http("POST", f"{EDGE}/tickets/classification", {"ticket_id": "TK-00042", "text": T42})
    time.sleep(0.5)
    result["helpdesk-app_pela_borda"] = {"status": edge["status"], "body": edge["body"],
                                         "novas_chamadas": len(calls()) - before}
    result["chaves"] = {"budget": key_info(BUDGET), "rate": key_info(RATE),
                        "helpdesk": key_info(HELPDESK)}
    return result


def exp_fallback_budget() -> dict:
    """Pré-condição: chave de orçamento esgotada. Falhas elegíveis nos destinos da F1."""
    provider_reset()
    result = {}
    fail("gpt-fake-large", "error_500")
    result["primario_500"] = proof(BUDGET, log_pattern=r"budget")
    fail("claude-fake-large", "error_500")
    result["dois_large_500"] = proof(BUDGET, log_pattern=r"budget")
    result["chamadas_por_modelo"] = {m: sum(c["model"] == m for c in calls()) for m in PRICES}
    provider_reset()
    return result


def exp_fallback_rate() -> dict:
    provider_reset()
    wait_window()
    fail("gpt-fake-large", "error_500")
    fail("claude-fake-large", "error_500")
    rows = []
    for _ in range(3):
        before = len(calls())
        response = chat(RATE)
        time.sleep(0.5)
        new = calls()[before:]
        rows.append({"status": response["status"], "headers": response["headers"],
                     "chamadas": [(c["model"], c["status"]) for c in new]})
    block = proof(RATE, log_pattern=r"rate limit|429")
    provider_reset()
    return {"dentro_do_limite_com_fallback": rows, "prova_bloqueio": block}


def exp_custo_cadeia() -> dict:
    """Custo e RPM de cadeias de fallback, pela chave de rate (orçamento US$ 1)."""
    provider_reset()
    wait_window()
    spend0 = key_info(RATE)["spend"]
    rows = []
    for scenario, failures in [("normal", []),
                               ("primario_500", [("gpt-fake-large", "error_500")]),
                               ("dois_large_500", [("gpt-fake-large", "error_500"),
                                                   ("claude-fake-large", "error_500")])]:
        provider_reset()
        for model, mode in failures:
            fail(model, mode)
        response = chat(RATE)
        time.sleep(0.5)
        attempts = []
        for c in calls():
            ok = c["status"] == 200 and c["output_tokens"] is not None
            attempts.append({"modelo": c["model"], "status": c["status"],
                             "tokens": (c["input_tokens"], c["output_tokens"]),
                             "custo_esperado": round(cost(c["model"], c["input_tokens"],
                                                          c["output_tokens"] or 0), 10) if ok else 0.0})
        rows.append({"cenario": scenario, "status": response["status"],
                     "headers": response["headers"], "tentativas": attempts,
                     "custo_esperado_total": round(sum(a["custo_esperado"] for a in attempts), 10)})
    provider_reset()
    time.sleep(FLUSH)
    spend1 = key_info(RATE)["spend"]
    # Mesma cadeia pela borda com a chave do helpdesk: gasto atribuído à identidade da app.
    h0 = key_info(HELPDESK)["spend"]
    fail("gpt-fake-large", "error_500")
    edge = http("POST", f"{EDGE}/tickets/classification", {"ticket_id": "TK-00042", "text": T42})
    edge_calls = [(c["model"], c["status"]) for c in calls()]
    provider_reset()
    time.sleep(FLUSH)
    h1 = key_info(HELPDESK)["spend"]
    return {"cadeias": rows, "gasto_chave_rate": {"antes": spend0, "depois": spend1,
                                                  "delta": round(spend1 - spend0, 10)},
            "borda_f1_primario_500": {"status": edge["status"], "chamadas": edge_calls,
                                      "gasto_helpdesk_antes": h0, "gasto_helpdesk_depois": h1,
                                      "delta": round(h1 - h0, 10)}}


def _burst(key: str, n: int) -> tuple[list[dict], int]:
    provider_reset()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda _: chat(key), range(n)))
    time.sleep(1.0)
    return results, len(calls())


def exp_concorrencia_budget(n: int = 6) -> dict:
    info0 = key_info(BUDGET)
    if info0["spend"] != 0:
        sys.exit("zere antes: docker compose run --rm gateway-bootstrap --reset-spend governance-budget-demo")
    results, provider_calls = _burst(BUDGET, n)
    time.sleep(FLUSH)
    after = key_info(BUDGET)
    follow = proof(BUDGET, log_pattern=r"budget")
    return {"iniciadas": n, "status": [r["status"] for r in results],
            "autorizadas": sum(r["status"] == 200 for r in results),
            "recusadas": sum(r["status"] != 200 for r in results),
            "recusas": [r["body"]["error"]["message"] for r in results
                        if r["status"] != 200 and isinstance(r["body"], dict)],
            "chamadas_ao_provider": provider_calls, "orcamento": info0["max_budget"],
            "gasto_registrado": after["spend"],
            "ultrapassagem": round(after["spend"] - info0["max_budget"], 10),
            "requisicao_seguinte": follow}


def exp_concorrencia_rate(n: int = 6) -> dict:
    wait_window()
    results, provider_calls = _burst(RATE, n)
    return {"iniciadas": n, "limite": key_info(RATE)["rpm_limit"],
            "status": [r["status"] for r in results],
            "autorizadas": sum(r["status"] == 200 for r in results),
            "recusadas": sum(r["status"] != 200 for r in results),
            "chamadas_ao_provider": provider_calls}


def exp_reserva_sequencial(repeticoes: int = 3, n: int = 8) -> dict:
    """Chave efêmera de US$ 0,0004; chamadas EM SEQUÊNCIA na mesma conexão, sem pausa.

    Mostra a reserva de orçamento: enquanto a reserva da chamada anterior não é liberada
    (logo depois da resposta), o saldo aparece cheio e a seguinte é recusada.
    """
    import http.client as httpclient
    import uuid
    body = json.dumps({"model": "ticket-classification",
                       "messages": [{"role": "user", "content": PROMPT_F1}]})
    runs = []
    for _ in range(repeticoes):
        provider_reset()
        key = f"sk-test-reserva-{uuid.uuid4().hex[:8]}"
        http("POST", f"{GATEWAY}/key/generate", {"key": key, "key_alias": f"test-reserva-{key[-8:]}",
                                                "models": ["ticket-classification"],
                                                "max_budget": 0.0004}, MASTER)
        conn = httpclient.HTTPConnection("localhost", 4000, timeout=30)
        seq = []
        for _ in range(n):
            conn.request("POST", "/v1/chat/completions", body,
                         {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            response = conn.getresponse()
            text = response.read().decode()
            match = re.search(r"Current cost: ([0-9.e-]+)", text)
            seq.append({"status": response.status,
                        "custo_visto_na_recusa": float(match.group(1)) if match else None})
        conn.close()
        time.sleep(1.0)
        runs.append({"sequencia": seq, "autorizadas": sum(s["status"] == 200 for s in seq),
                     "chamadas_ao_provider": len(calls())})
        http("POST", f"{GATEWAY}/key/delete", {"keys": [key]}, MASTER)
    return {"orcamento": 0.0004, "custo_f1": 0.0001575, "execucoes": runs}


def exp_latencia(n: int = 8) -> dict:
    provider_reset()
    out = {}
    for label, key in (("master", MASTER), ("helpdesk-app", HELPDESK)):
        samples = [chat(key) for _ in range(n)]
        overhead = sorted(float(s["headers"]["x-litellm-overhead-duration-ms"]) for s in samples)
        total = sorted(s["elapsed_s"] for s in samples)
        out[label] = {"overhead_ms_mediana": overhead[n // 2], "overhead_ms_max": overhead[-1],
                      "total_s_mediana": total[n // 2], "total_s_max": total[-1]}
    edge = sorted(http("POST", f"{EDGE}/tickets/classification",
                       {"ticket_id": "TK-00042", "text": T42})["elapsed_s"] for _ in range(n))
    out["f1_pela_borda"] = {"mediana_s": edge[n // 2], "max_s": edge[-1], "n": n}
    return out


EXPERIMENTS = {"precos": exp_precos, "autenticacao": exp_autenticacao, "budget": exp_budget,
               "rate": exp_rate, "isolamento": exp_isolamento,
               "fallback-budget": exp_fallback_budget, "fallback-rate": exp_fallback_rate,
               "custo-cadeia": exp_custo_cadeia, "concorrencia-budget": exp_concorrencia_budget,
               "concorrencia-rate": exp_concorrencia_rate,
               "reserva-sequencial": exp_reserva_sequencial, "latencia": exp_latencia}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experimento", choices=EXPERIMENTS)
    parser.add_argument("--saida")
    args = parser.parse_args()
    started = now()
    try:
        result = EXPERIMENTS[args.experimento]()
    finally:
        provider_reset()
    payload = {"experimento": args.experimento, "inicio": started, "fim": now(), "resultado": result}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.saida:
        path = OUT / args.saida
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"gravado em {path.relative_to(ROOT)}")
    print(text)


if __name__ == "__main__":
    main()
