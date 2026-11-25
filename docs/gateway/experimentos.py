"""Experimentos do Passo 07: o AI Gateway (LiteLLM Proxy) validado de forma isolada.

Fala direto com o gateway e com o provider-fake (sem passar pela app) e imprime JSON
com as evidências: respostas, status, tempos e o registro de /admin/calls. Usa só a
biblioteca padrão, para rodar em qualquer python:3.12-slim.

Uso (na raiz do repositório, com o compose no ar):

    docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
      -e GATEWAY_URL=http://host.docker.internal:4000 \
      -e PROVIDER_URL=http://host.docker.internal:8090 \
      python:3.12-slim python docs/gateway/experimentos.py FASE

Fases: probe, auth, capacidades, normalizacao, erros, latencia, streaming, retries.

Atenção: toda fase começa com POST /admin/reset (limpa o registro de chamadas e volta
o provider ao modo normal). A fase "retries" liga um modo de falha e o desliga no fim.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:4000")
PROVIDER = os.environ.get("PROVIDER_URL", "http://localhost:8090")
GATEWAY_KEY = os.environ.get("GATEWAY_MASTER_KEY", "sk-gateway-local-0001")
OPENAI_KEY = os.environ.get("FAKE_OPENAI_KEY", "sk-fake-openai-0001")
ANTHROPIC_KEY = os.environ.get("FAKE_ANTHROPIC_KEY", "sk-ant-fake-0001")
ROOT = Path(__file__).resolve().parents[2]
EXPECTED = ROOT / "tests" / "characterization" / "expected"

# Mesmas entradas da caracterização (Passo 04).
T42 = "Meu pedido #481516 não chegou e já passou do prazo, urgente"
T200 = "Pedido #481516, o fone de ouvido bluetooth veio com chiado"


# ---------------------------------------------------------------- HTTP

def http(method: str, url: str, body: dict | None = None, headers: dict | None = None,
         timeout: float = 120) -> tuple[int, dict | str, float]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    elapsed = round(time.monotonic() - t0, 3)
    try:
        return status, json.loads(raw), elapsed
    except ValueError:
        return status, raw.decode("utf-8", "replace"), elapsed


def reset() -> None:
    http("POST", f"{PROVIDER}/admin/reset")


def calls(last: int = 50) -> list[dict]:
    _, body, _ = http("GET", f"{PROVIDER}/admin/calls?last={last}")
    return body if isinstance(body, list) else body.get("calls", body)


def gateway(capability: str, content: str, key: str | None = GATEWAY_KEY, **extra):
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    body = {"model": capability, "messages": [{"role": "user", "content": content}], **extra}
    return http("POST", f"{GATEWAY}/v1/chat/completions", body, headers)


def openai_direct(model: str, content: str, **extra):
    body = {"model": model, "messages": [{"role": "user", "content": content}], **extra}
    return http("POST", f"{PROVIDER}/openai/v1/chat/completions", body,
                {"Authorization": f"Bearer {OPENAI_KEY}"})


def anthropic_direct(model: str, content: str, max_tokens: int = 2000, **extra):
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}], **extra}
    return http("POST", f"{PROVIDER}/anthropic/v1/messages", body,
                {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})


def content_of(body) -> str | None:
    """Texto gerado, no formato OpenAI (gateway) ou Messages (Anthropic nativo)."""
    if not isinstance(body, dict):
        return None
    if "choices" in body:
        return body["choices"][0]["message"]["content"]
    if "content" in body and isinstance(body["content"], list):
        return "".join(part.get("text", "") for part in body["content"])
    return None


def summary(status, body, elapsed) -> dict:
    out = {"status": status, "seconds": elapsed}
    if isinstance(body, dict) and ("choices" in body or "content" in body):
        out["content"] = content_of(body)
        out["model_field"] = body.get("model")
        out["usage"] = body.get("usage")
        if "choices" in body:
            out["finish_reason"] = body["choices"][0].get("finish_reason")
        else:
            out["stop_reason"] = body.get("stop_reason")
        out["top_level_keys"] = sorted(body.keys())
    else:
        out["body"] = body
    return out


def topics_content(day: str) -> tuple[str, int]:
    """Monta o lote da F3 exatamente como report.py faz para um dia (um lote só)."""
    target = date.fromisoformat(day)
    lines = []
    with open(ROOT / "data" / "tickets.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if datetime.fromisoformat(t["created_at"]).date() == target:
                lines.append(f"[{t['id']}] {t['text']}")
    assert len(lines) <= 150, "o golden usa um único lote"
    return "\n".join(lines), len(lines)


def aggregate_like_report(answer: dict) -> list[dict]:
    """Mesma agregação e ordenação de report.py, para comparar com o golden."""
    totals: dict[str, dict] = {}
    for item in answer["topics"]:
        cur = totals.setdefault(item["topic"], {"count": 0, "examples": []})
        cur["count"] += item["count"]
        cur["examples"] = (cur["examples"] + item["examples"])[:3]
    items = [{"topic": k, **v} for k, v in totals.items()]
    items.sort(key=lambda t: (-t["count"], t["topic"]))
    return items


# ---------------------------------------------------------------- fases

def fase_probe() -> dict:
    """Uma chamada a ticket-classification e o registro do provider (etapas e troca de modelo)."""
    reset()
    r = summary(*gateway("ticket-classification", f"TASK: classify\n{T42}"))
    return {"gateway": r, "admin_calls": calls(5)}


def fase_auth() -> dict:
    reset()
    out = {}
    for nome, key in (("chave_valida", GATEWAY_KEY), ("chave_invalida", "sk-errada-0000"),
                      ("sem_chave", None)):
        before = len(calls(5000))
        status, body, elapsed = gateway("ticket-classification", f"TASK: classify\n{T42}", key=key)
        after = len(calls(5000))
        out[nome] = {"status": status, "seconds": elapsed,
                     "body": body if status != 200 else content_of(body),
                     "chamadas_no_provider": after - before}
    out["admin_calls"] = calls(10)
    return out


def fase_capacidades() -> dict:
    reset()
    out = {}

    s, b, e = gateway("ticket-classification", f"TASK: classify\n{T42}")
    data = json.loads(content_of(b))
    out["ticket-classification"] = {**summary(s, b, e), "esperado": {"category": "delivery", "priority": "high"},
                                    "confere": data == {"category": "delivery", "priority": "high"}}

    s, b, e = gateway("order-extraction", f"TASK: extract\n{T200}")
    data = json.loads(content_of(b))
    esperado = {"order_number": "#481516", "product": "fone de ouvido bluetooth"}
    out["order-extraction"] = {**summary(s, b, e), "esperado": esperado, "confere": data == esperado}

    golden = json.loads((EXPECTED / "reply_suggestion_TK-00042.json").read_text(encoding="utf-8"))
    s, b, e = gateway("reply-suggestion", f"TASK: suggest\n{T42}")
    texto = content_of(b)
    out["reply-suggestion"] = {**summary(s, b, e), "content": f"{len(texto)} caracteres",
                               "igual_ao_golden_byte_a_byte": texto == golden["body"]["suggestion"]}

    golden = json.loads((EXPECTED / "topics_2026-08-01.json").read_text(encoding="utf-8"))
    conteudo, n = topics_content("2026-08-01")
    s, b, e = gateway("topics-report", f"TASK: topics\n{conteudo}")
    agregado = aggregate_like_report(json.loads(content_of(b)))
    out["topics-report"] = {**summary(s, b, e), "content": f"{len(agregado)} temas",
                            "tickets_no_lote": n,
                            "igual_ao_golden_apos_agregacao": agregado == golden["body"]["topics"]
                            and n == golden["body"]["total_tickets"]}

    out["admin_calls"] = calls(10)
    return out


def fase_normalizacao() -> dict:
    """A mesma tarefa num destino OpenAI e num Anthropic, pela interface do gateway e nativa."""
    reset()
    tarefa = f"TASK: classify\n{T42}"
    out = {
        "openai_nativo": summary(*openai_direct("gpt-fake-large", tarefa)),
        "anthropic_nativo": summary(*anthropic_direct("claude-fake-large", tarefa)),
        # reply-suggestion aponta para claude-fake-large; a tarefa classify é só para comparar.
        "gateway_destino_openai": summary(*gateway("ticket-classification", tarefa)),
        "gateway_destino_anthropic": summary(*gateway("reply-suggestion", tarefa)),
    }
    out["admin_calls"] = calls(10)
    return out


def fase_erros() -> dict:
    """Erros com o mesmo gatilho nos dois providers: entrada maior que o contexto (8.000 tokens)."""
    reset()
    grande = "TASK: classify\n" + ("x" * 40000)
    out = {
        "openai_nativo": http("POST", f"{PROVIDER}/openai/v1/chat/completions",
                              {"model": "gpt-fake-large", "messages": [{"role": "user", "content": grande}]},
                              {"Authorization": f"Bearer {OPENAI_KEY}"})[:2],
        "anthropic_nativo": anthropic_direct("claude-fake-large", grande)[:2],
        "gateway_destino_openai": gateway("ticket-classification", grande)[:2],
        "gateway_destino_anthropic": gateway("reply-suggestion", grande)[:2],
        "gateway_capacidade_inexistente": gateway("capacidade-que-nao-existe", "TASK: classify\nx")[:2],
    }
    out["admin_calls"] = calls(10)
    return out


def fase_latencia(reps_classify: int = 5, reps_suggest: int = 3) -> dict:
    reset()
    gateway("ticket-classification", f"TASK: classify\n{T42}")        # aquecimento
    openai_direct("gpt-fake-large", f"TASK: classify\n{T42}")
    out = {}
    for nome, direto, via in (
        ("classify gpt-fake-large", lambda: openai_direct("gpt-fake-large", f"TASK: classify\n{T42}"),
         lambda: gateway("ticket-classification", f"TASK: classify\n{T42}")),
        ("suggest claude-fake-large", lambda: anthropic_direct("claude-fake-large", f"TASK: suggest\n{T42}"),
         lambda: gateway("reply-suggestion", f"TASK: suggest\n{T42}")),
    ):
        reps = reps_classify if nome.startswith("classify") else reps_suggest
        d, g = [], []
        for _ in range(reps):          # alternados, para dividir variações do ambiente
            d.append(direto()[2])
            g.append(via()[2])
        out[nome] = {"direto_s": d, "gateway_s": g,
                     "mediana_direto": sorted(d)[len(d) // 2], "mediana_gateway": sorted(g)[len(g) // 2]}
    out["admin_calls_ultimas"] = calls(4)
    return out


def _stream(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    t0 = time.monotonic()
    first_byte = first_content = None
    eventos, texto, ultimo = 0, [], None
    with urllib.request.urlopen(req, timeout=120) as r:
        status = r.status
        ctype = r.headers.get("Content-Type")
        for raw in r:
            agora = time.monotonic() - t0
            first_byte = first_byte if first_byte is not None else agora
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            eventos += 1
            payload = line[5:].strip()
            ultimo = payload[:200]
            if payload == "[DONE]":
                continue
            ev = json.loads(payload)
            pedaco = ""
            if "choices" in ev and ev["choices"]:
                pedaco = ev["choices"][0].get("delta", {}).get("content") or ""
            elif ev.get("type") == "content_block_delta":
                pedaco = ev["delta"].get("text", "")
            if pedaco:
                first_content = first_content if first_content is not None else agora
                texto.append(pedaco)
    return {"status": status, "content_type": ctype, "primeiro_byte_s": round(first_byte or 0, 3),
            "primeiro_conteudo_s": round(first_content or 0, 3),
            "total_s": round(time.monotonic() - t0, 3), "eventos_data": eventos,
            "ultimo_evento": ultimo, "caracteres": len("".join(texto)), "texto": "".join(texto)}


def fase_streaming() -> dict:
    reset()
    golden = json.loads((EXPECTED / "reply_suggestion_TK-00042.json").read_text(encoding="utf-8"))
    via = _stream(f"{GATEWAY}/v1/chat/completions",
                  {"model": "reply-suggestion", "stream": True,
                   "messages": [{"role": "user", "content": f"TASK: suggest\n{T42}"}]},
                  {"Authorization": f"Bearer {GATEWAY_KEY}"})
    direto = _stream(f"{PROVIDER}/anthropic/v1/messages",
                     {"model": "claude-fake-large", "max_tokens": 2000, "stream": True,
                      "messages": [{"role": "user", "content": f"TASK: suggest\n{T42}"}]},
                     {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})
    for r in (via, direto):
        r["igual_ao_golden"] = r.pop("texto") == golden["body"]["suggestion"]
    return {"gateway": via, "anthropic_nativo": direto, "admin_calls": calls(4)}


def fase_retries() -> dict:
    """Quantas chamadas chegam ao provider quando ele falha? (padrão do gateway, sem configurar retry)"""
    reset()
    http("POST", f"{PROVIDER}/admin/failures", {"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"})
    try:
        status, body, elapsed = gateway("ticket-classification", f"TASK: classify\n{T42}")
        registro = calls(20)
    finally:
        reset()
    return {"status": status, "seconds": elapsed, "body": body,
            "chamadas_no_provider": len(registro), "admin_calls": registro}


FASES = {name[5:]: fn for name, fn in globals().items() if name.startswith("fase_")}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in FASES:
        sys.exit(f"uso: experimentos.py {{{','.join(FASES)}}}")
    print(json.dumps({"fase": sys.argv[1], "quando": datetime.now().isoformat(timespec="seconds"),
                      "resultado": FASES[sys.argv[1]]()}, ensure_ascii=False, indent=2))
