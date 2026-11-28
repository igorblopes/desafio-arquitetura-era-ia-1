"""Sondas do Passo 13: execução síncrona de F1 e F4 medida pela borda.

Cada subcomando roda um experimento contra o ambiente real do docker compose (borda 8000,
app, gateway, provider-fake 8090), grava a evidência em JSON em docs/execucao/evidencias/ e
imprime um resumo. Nada de mock: o tempo é o que o cliente vê na borda e as chamadas são as
que o provider registrou em /admin/calls.

    python docs/execucao/sondas_execucao.py <experimento>

Experimentos: baseline, normal-f1, normal-f4, invalidas, error500, timeout, slow, error429,
larges-500, providers-500, providers-timeout, concorrencia, deadline (com o gateway
pausado pelo operador), governanca <rotulo> (com a app recriada com outra chave).

Tempo: TTFB = do envio até chegarem os cabeçalhos da resposta (a resposta síncrona só manda
bytes no fim, então TTFB ~ tempo total); total = até o último byte do corpo.
O provider é estado global: rode um experimento por vez e nunca em paralelo com as suítes.
"""

import json
import os
import pathlib
import statistics
import sys
import threading
import time
from datetime import datetime, timezone

import httpx

EDGE = os.environ.get("HELPDESK_BASE_URL", "http://localhost:8000")
PROVIDER = os.environ.get("PROVIDER_ADMIN_URL", "http://localhost:8090")
OUT = pathlib.Path(__file__).resolve().parent / "evidencias"

GPT_L, CLA_L, GPT_M, CLA_M = "gpt-fake-large", "claude-fake-large", "gpt-fake-mini", "claude-fake-mini"
PROVIDER_OF = {GPT_L: "openai", GPT_M: "openai", CLA_L: "anthropic", CLA_M: "anthropic"}

F1 = ("/tickets/classification", "classify")
F4 = ("/tickets/extraction", "extract")
FEATURES = {"F1": F1, "F4": F4}

T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T_DEVOLVER = "Quero devolver o teclado do pedido #481516."
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"

# Entradas representativas: as mesmas da caracterização (tests/characterization).
F1_INPUTS = [
    ("TK-00042", T42),
    ("TK-00100", "Fui cobrado duas vezes no cartão pela mesma compra"),
    ("TK-00101", "Quero trocar a camiseta básica por um tamanho maior, sem pressa"),
    ("TK-00102", "O liquidificador chegou quebrado e não liga"),
    ("TK-00103", "Como faço para alterar meu e-mail de cadastro?"),
    ("TK-00104", "Não é urgente, só queria saber se vocês têm loja física"),
    ("TK-00105", "Quando puder, me informe o prazo de entrega, sem pressa nenhuma"),
    ("TK-00106", "Dúvida simples: posso pagar com dois cartões?"),
    ("TK-00107", "Obrigado, o problema já foi resolvido, podem fechar o chamado"),
]
# (id, texto, rótulo do caso)
F4_INPUTS = [
    ("TK-00042", T_DEVOLVER, "exemplo do enunciado (produto citado só como 'teclado')"),
    ("TK-00200", T200, "pedido e produto presentes"),
    ("TK-00201", "O protocolo #12345 não resolveu, o aspirador robô continua sem funcionar",
     "pedido ausente, produto presente"),
    ("TK-00042", T42, "pedido presente, produto ausente"),
    ("TK-00202", "Como faço para alterar meu e-mail de cadastro?", "pedido e produto ausentes"),
    ("TK-00203", "Meu pedido 481516 não chegou", "número sem cerquilha"),
    ("TK-00204", "O pedido #4815162 veio com o produto errado", "sete dígitos não é pedido"),
]

edge = httpx.Client(base_url=EDGE, timeout=httpx.Timeout(60.0, connect=5.0))
provider = httpx.Client(base_url=PROVIDER, timeout=10.0)


# ------------------------------------------------------------------ utilidades

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def reset() -> None:
    provider.post("/admin/reset").raise_for_status()


def fail(model: str | None, mode: str, prov: str | None = None) -> None:
    body = {"provider": prov or PROVIDER_OF[model], "mode": mode}
    if model is not None:
        body["model"] = model
    provider.post("/admin/failures", json=body).raise_for_status()


def calls(task: str | None = None) -> list[dict]:
    body = provider.get("/admin/calls", params={"last": 500}).json()
    if task is not None:
        body = [c for c in body if c["task"] == task]
    return sorted(body, key=lambda c: c["ts"])


def failures() -> dict:
    return provider.get("/admin/failures").json()


def post(path: str, body=None, raw: bytes | None = None, client: httpx.Client = edge) -> dict:
    """POST pela borda medindo TTFB (cabeçalhos) e tempo total (corpo inteiro)."""
    kwargs = {"content": raw, "headers": {"Content-Type": "application/json"}} if raw is not None \
        else {"json": body}
    start = time.perf_counter()
    with client.stream("POST", path, **kwargs) as response:
        ttfb = time.perf_counter() - start
        content = response.read()
        total = time.perf_counter() - start
    text = content.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    ctype = response.headers.get("content-type", "")
    return {
        "status": response.status_code,
        "ttfb_s": round(ttfb, 3),
        "total_s": round(total, 3),
        "body": parsed if parsed is not None else text[:300],
        "content_type": ctype,
        "retry_after": response.headers.get("retry-after"),
        # O 504 da borda é HTML do nginx; os erros da app são JSON com "detail".
        "edge_504": response.status_code == 504 and "html" in ctype,
    }


def slim(call: dict) -> dict:
    return {k: call[k] for k in ("ts", "provider", "model", "task", "status",
                                 "input_tokens", "output_tokens", "duration_ms")}


def wait_settled(task: str, limit: float = 20.0) -> list[dict]:
    """Espera as chamadas da tarefa pararem de mudar (cadeia do gateway terminada)."""
    deadline = time.monotonic() + limit
    last = None
    while time.monotonic() < deadline:
        current = [(c["model"], c["status"], c["duration_ms"]) for c in calls(task)]
        if current == last:
            break
        last = current
        time.sleep(1.0)
    return [slim(c) for c in calls(task)]


def stats(values: list[float]) -> dict:
    ordered = sorted(values)
    result = {
        "n": len(ordered),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
        "media": round(statistics.mean(ordered), 3),
        "mediana": round(statistics.median(ordered), 3),
    }
    if len(ordered) >= 20:  # abaixo disso o p95 seria só o máximo com outro nome
        result["p95"] = round(statistics.quantiles(ordered, n=20, method="inclusive")[-1], 3)
    if len(ordered) >= 100:
        result["p99"] = round(statistics.quantiles(ordered, n=100, method="inclusive")[-1], 3)
    return result


def save(name: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {"gerado_em": now(), "borda": EDGE, **data}
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"evidência: {path.relative_to(OUT.parents[2])}")


# ------------------------------------------------------------------ experimentos

def baseline() -> None:
    """Primeira chamada após a inicialização da app e chamadas seguintes, F1 e F4."""
    reset()
    runs = []
    for feature, body in (("F1", {"ticket_id": "TK-00042", "text": T42}),
                          ("F4", {"ticket_id": "TK-00042", "text": T_DEVOLVER})):
        path, task = FEATURES[feature]
        for i in range(6):
            before = len(calls(task))
            r = post(path, body)
            new = [slim(c) for c in calls(task)][before:]
            runs.append({"feature": feature, "execucao": i + 1,
                         "primeira_apos_inicio": i == 0, **r, "chamadas": new})
            print(feature, i + 1, r["status"], r["ttfb_s"], r["total_s"], r["body"],
                  [(c["model"], c["status"], c["input_tokens"], c["output_tokens"]) for c in new])
    summary = {}
    for feature in ("F1", "F4"):
        mine = [r for r in runs if r["feature"] == feature]
        summary[feature] = {"primeira": mine[0]["total_s"],
                            "seguintes": stats([r["total_s"] for r in mine[1:]])}
    save("01-baseline", {"descricao": "app recém-reiniciada; 6 chamadas seguidas de F1 e F4",
                         "resumo": summary, "execucoes": runs})
    reset()


def normal(feature: str) -> None:
    reset()
    path, task = FEATURES[feature]
    rounds = 3 if feature == "F1" else 3
    inputs = F1_INPUTS if feature == "F1" else [(i, t) for i, t, _ in F4_INPUTS]
    labels = {} if feature == "F1" else {(i, t): label for i, t, label in F4_INPUTS}
    runs = []
    for round_ in range(rounds):
        for ticket_id, text in inputs:
            before = len(calls(task))
            r = post(path, {"ticket_id": ticket_id, "text": text})
            new = [slim(c) for c in calls(task)][before:]
            runs.append({"rodada": round_ + 1, "ticket_id": ticket_id, "texto": text,
                         "caso": labels.get((ticket_id, text)), **r, "chamadas": new})
            print(feature, round_ + 1, ticket_id, r["status"], r["total_s"], r["body"],
                  [(c["model"], c["status"]) for c in new])
    # Série extra só com o exemplo do enunciado, para ter amostra >= 20 numa mesma entrada.
    reference = {"ticket_id": "TK-00042", "text": T42 if feature == "F1" else T_DEVOLVER}
    series = []
    for _ in range(20):
        series.append(post(path, reference)["total_s"])
    totals = [r["total_s"] for r in runs]
    over = [r for r in runs if feature == "F1" and r["total_s"] > 3.0]
    extra_calls = [r for r in runs if len(r["chamadas"]) != 1 or r["chamadas"][0]["model"] != GPT_L]
    save(f"02-normal-{feature.lower()}", {
        "descricao": f"{feature} em modo normal: entradas da caracterização x {rounds} rodadas "
                     "+ 20 repetições do exemplo do enunciado",
        "resumo_entradas": stats(totals),
        "resumo_exemplo_20x": stats(series),
        "serie_exemplo_20x": series,
        "acima_de_3s": len(over),
        "execucoes_com_chamada_extra_ou_fora_do_primario": len(extra_calls),
        "execucoes": runs,
    })
    reset()


INVALID = [
    ("corpo vazio", {}, None),
    ("sem ticket_id", {"text": "x"}, None),
    ("sem text", {"ticket_id": "TK-1"}, None),
    ("ticket_id vazio", {"ticket_id": "", "text": "x"}, None),
    ("text vazio", {"ticket_id": "TK-1", "text": ""}, None),
    ("text numérico", {"ticket_id": "TK-1", "text": 123}, None),
    ("ticket_id numérico", {"ticket_id": 42, "text": "x"}, None),
    ("text nulo", {"ticket_id": "TK-1", "text": None}, None),
    ("corpo é lista", [], None),
    ("JSON malformado", None, b'{"ticket_id": "TK-1", "text": '),
]


def invalidas() -> None:
    reset()
    runs = []
    for feature, (path, task) in FEATURES.items():
        for label, body, raw in INVALID:
            before = len(calls())
            r = post(path, body, raw)
            time.sleep(0.2)
            after = len(calls())
            runs.append({"feature": feature, "entrada": label, **r,
                         "chamadas_ao_provider": after - before})
            print(feature, label, r["status"], r["total_s"], after - before)
    save("03-entradas-invalidas", {"descricao": "entradas inválidas pela borda; contagem de "
                                   "/admin/calls antes e depois de cada uma",
                                   "execucoes": runs})
    reset()


def failure_scenario(name: str, description: str, setup, features=("F1", "F4"),
                     body_for=None, repeat: int = 1) -> None:
    runs = []
    for feature in features:
        path, task = FEATURES[feature]
        body = (body_for or {}).get(feature) or (
            {"ticket_id": "TK-00042", "text": T42} if feature == "F1"
            else {"ticket_id": "TK-00200", "text": T200})
        for i in range(repeat):
            reset()
            setup()
            config = failures()["effective_by_model"]
            r = post(path, body)
            chain = wait_settled(task)
            runs.append({"feature": feature, "execucao": i + 1, "modos": config, **r,
                         "chamadas": chain})
            print(feature, i + 1, r["status"], r["total_s"], r["body"],
                  [(c["model"], c["status"]) for c in chain])
    reset()
    save(name, {"descricao": description, "execucoes": runs})


def error500() -> None:
    failure_scenario("04-primario-500", "primário (gpt-fake-large) em error_500",
                     lambda: fail(GPT_L, "error_500"), repeat=3)


def timeout() -> None:
    failure_scenario("05-primario-timeout", "primário (gpt-fake-large) em timeout (segura 300 s)",
                     lambda: fail(GPT_L, "timeout"), repeat=3)


def slow() -> None:
    failure_scenario("06-primario-slow", "primário (gpt-fake-large) em slow (10x mais lento)",
                     lambda: fail(GPT_L, "slow"), repeat=2)


def error429() -> None:
    failure_scenario("07-primario-429", "primário (gpt-fake-large) em error_429 (Retry-After: 2)",
                     lambda: fail(GPT_L, "error_429"), repeat=2)


def larges_500() -> None:
    def setup():
        fail(GPT_L, "error_500")
        fail(CLA_L, "error_500")
    failure_scenario("08-larges-500", "os dois large em error_500; mini no ar", setup, repeat=2)


def providers_500() -> None:
    def setup():
        fail(None, "error_500", "openai")
        fail(None, "error_500", "anthropic")
    failure_scenario("09-providers-500", "os dois providers inteiros em error_500", setup, repeat=2)


def providers_timeout() -> None:
    def setup():
        fail(None, "timeout", "openai")
        fail(None, "timeout", "anthropic")
    failure_scenario("10-providers-timeout", "os dois providers inteiros em timeout (pior caso "
                     "temporal)", setup, repeat=2)


def deadline() -> None:
    """F1 e F4 com o GATEWAY congelado (o operador roda `docker compose pause gateway` antes).

    A conexão TCP abre (o kernel aceita), mas nenhum byte volta: só o deadline global da app
    (14 s, config.GATEWAY_DEADLINE_SECONDS) pode encerrar a espera. Nenhum provider é chamado.
    """
    before = len(calls())
    runs = []
    for feature, body in (("F1", {"ticket_id": "TK-00042", "text": T42}),
                          ("F4", {"ticket_id": "TK-00200", "text": T200})):
        r = post(FEATURES[feature][0], body)
        runs.append({"feature": feature, **r})
        print(feature, r["status"], r["total_s"], r["body"], r["edge_504"])
    save("13-gateway-congelado-deadline", {
        "descricao": "gateway congelado (docker compose pause gateway): deadline global da app",
        "chamadas_ao_provider": len(calls()) - before, "execucoes": runs})


def governanca(label: str) -> None:
    """Uma F1 e uma F4 pela borda com a app usando a chave que o operador configurou.

    O operador recria só a app com outra GATEWAY_API_KEY antes (ver relatório, seção 4.34);
    esta sonda só mede e conta /admin/calls antes e depois, sem reset no meio.
    """
    reset()
    before = len(calls())
    runs = []
    for feature, body in (("F1", {"ticket_id": "TK-00042", "text": T42}),
                          ("F4", {"ticket_id": "TK-00200", "text": T200})):
        path, _ = FEATURES[feature]
        b = len(calls())
        r = post(path, body)
        time.sleep(0.5)
        runs.append({"feature": feature, **r, "chamadas_novas_ao_provider": len(calls()) - b})
        print(label, feature, r["status"], r["total_s"], r["body"], r["retry_after"],
              len(calls()) - b)
    save(f"11-governanca-{label}", {"descricao": f"recusa de governança pela borda: {label}",
                                    "chamadas_antes": before, "chamadas_depois": len(calls()),
                                    "execucoes": runs})


def concorrencia() -> None:
    """Rajadas pequenas de F1 simultâneas; /health medido durante a maior rajada."""
    reset()
    levels = [1, 5, 10, 20, 40, 60]
    result = []
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    for level in levels:
        time.sleep(2)
        client = httpx.Client(base_url=EDGE, timeout=httpx.Timeout(60.0, connect=5.0), limits=limits)
        barrier = threading.Barrier(level + 1)
        outcomes: list[dict] = []
        lock = threading.Lock()

        def worker(index: int) -> None:
            barrier.wait()
            r = post("/tickets/classification",
                     {"ticket_id": f"TK-C{index:03d}", "text": T42}, client=client)
            with lock:
                outcomes.append(r)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(level)]
        for t in threads:
            t.start()
        health = []
        start = time.perf_counter()
        barrier.wait()
        if level >= 40:  # /health também é rota `def`: precisa de uma thread do pool
            time.sleep(0.3)
            for _ in range(3):
                t0 = time.perf_counter()
                edge.get("/health")
                health.append(round(time.perf_counter() - t0, 3))
                time.sleep(0.2)
        for t in threads:
            t.join()
        wall = time.perf_counter() - start
        client.close()
        latencies = [o["total_s"] for o in outcomes]
        ok = [o for o in outcomes if o["status"] == 200]
        result.append({
            "simultaneas": level, "sucessos": len(ok), "falhas": level - len(ok),
            "status": sorted({o["status"] for o in outcomes}),
            "latencia": stats(latencies), "tempo_do_conjunto_s": round(wall, 3),
            "health_durante_s": health,
        })
        print(level, len(ok), stats(latencies), round(wall, 3), health)
    total_calls = calls("classify")
    save("12-concorrencia", {
        "descricao": "rajadas de F1 simultâneas pela borda (exemplo TK-00042), modo normal",
        "niveis": result,
        "chamadas_ao_provider": len(total_calls),
        "modelos": sorted({c["model"] for c in total_calls}),
        "status_no_provider": sorted({c["status"] for c in total_calls}),
    })
    reset()


COMMANDS = {
    "baseline": baseline,
    "normal-f1": lambda: normal("F1"),
    "normal-f4": lambda: normal("F4"),
    "invalidas": invalidas,
    "error500": error500,
    "timeout": timeout,
    "slow": slow,
    "error429": error429,
    "larges-500": larges_500,
    "providers-500": providers_500,
    "providers-timeout": providers_timeout,
    "concorrencia": concorrencia,
    "deadline": deadline,
}

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "governanca":
        governanca(sys.argv[2] if len(sys.argv) > 2 else "sem-rotulo")
    elif len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"uso: {sys.argv[0]} {{{'|'.join(COMMANDS)}|governanca <rotulo>}}")
    else:
        COMMANDS[sys.argv[1]]()
