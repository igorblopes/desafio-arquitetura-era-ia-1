"""Passo 11: large x mini com mais casos do que o Passo 03, direto no provider-fake.

Mesma entrada, os quatro modelos, sem passar pelo gateway. Objetivo: evidência específica
do modelo `mini` que seria usado como fallback degradado em cada feature. Só biblioteca
padrão. O script faz /admin/reset no começo e no fim.

Uso (raiz do repositório, compose no ar):

    python docs/fallback/comparar_modelos.py [--amostra 1000] [--saida docs/fallback/evidencias/comparacao-modelos.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROVIDER = "http://localhost:8090"
KEYS = {"openai": "sk-fake-openai-0001", "anthropic": "sk-ant-fake-0001"}
MODELS = {
    "gpt-fake-large": "openai",
    "claude-fake-large": "anthropic",
    "gpt-fake-mini": "openai",
    "claude-fake-mini": "anthropic",
}
ROOT = pathlib.Path(__file__).resolve().parents[2]
BATCH = 150  # mesmo lote da app (config.TICKETS_PER_CALL)
ORDER = re.compile(r"#\d{6}\b")


def _post(url: str, body: dict, headers: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def complete(model: str, prompt: str) -> str:
    provider = MODELS[model]
    if provider == "openai":
        body = _post(f"{PROVIDER}/openai/v1/chat/completions",
                     {"model": model, "max_tokens": 2000,
                      "messages": [{"role": "user", "content": prompt}]},
                     {"Authorization": f"Bearer {KEYS[provider]}"})
        return body["choices"][0]["message"]["content"]
    body = _post(f"{PROVIDER}/anthropic/v1/messages",
                 {"model": model, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]},
                 {"x-api-key": KEYS[provider], "anthropic-version": "2023-06-01"})
    return body["content"][0]["text"]


def run_all(prompts: list[str]) -> dict[str, list[str]]:
    jobs = [(m, p) for m in MODELS for p in prompts]
    with ThreadPoolExecutor(max_workers=48) as pool:
        results = list(pool.map(lambda job: complete(*job), jobs))
    out: dict[str, list[str]] = {m: [] for m in MODELS}
    for (model, _), text in zip(jobs, results):
        out[model].append(text)
    return out


def tickets() -> list[dict]:
    with open(ROOT / "data" / "tickets.jsonl", encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def compare_short(task: str, sample: list[dict]) -> dict:
    out = run_all([f"TASK: {task}\n{t['text']}" for t in sample])
    parsed = {m: [json.loads(x) for x in texts] for m, texts in out.items()}
    ref = parsed["gpt-fake-large"]
    summary: dict = {"casos": len(sample)}
    for model in MODELS:
        diffs = [i for i, (a, b) in enumerate(zip(ref, parsed[model])) if a != b]
        per_field: collections.Counter = collections.Counter()
        kinds: collections.Counter = collections.Counter()
        for i in diffs:
            for field in ref[i]:
                if ref[i][field] != parsed[model][i][field]:
                    per_field[field] += 1
                    kinds[f"{field}: {ref[i][field]!r} -> {parsed[model][i][field]!r}"] += 1
        summary[model] = {
            "iguais_ao_gpt_large": len(sample) - len(diffs),
            "diferentes": len(diffs),
            "diferencas_por_campo": dict(per_field),
            "tipos_mais_comuns": kinds.most_common(10),
            "exemplos": [{"ticket": sample[i]["id"], "texto": sample[i]["text"][:160],
                          "large": ref[i], "modelo": parsed[model][i]} for i in diffs[:4]],
        }
    if task == "extract":
        summary["large_com_produto"] = sum(1 for r in ref if r["product"] is not None)
        summary["large_com_pedido"] = sum(1 for r in ref if r["order_number"] is not None)
        for model in MODELS:
            summary[model]["produto_nulo_quando_large_extraiu"] = sum(
                1 for a, b in zip(ref, parsed[model]) if a["product"] is not None and b["product"] is None)
    if task == "classify":
        for model in MODELS:
            summary[model]["prioridades"] = dict(collections.Counter(p["priority"] for p in parsed[model]))
            summary[model]["categorias"] = dict(collections.Counter(p["category"] for p in parsed[model]))
    return summary


def compare_topics(all_tickets: list[dict], days: list[str]) -> dict:
    prompts, labels = [], []
    for day in days:
        selected = [t for t in all_tickets if t["created_at"].startswith(day)]
        for first in range(0, len(selected), BATCH):
            batch = selected[first:first + BATCH]
            prompts.append("TASK: topics\n" + "\n".join(f"[{t['id']}] {t['text']}" for t in batch))
            labels.append({"dia": day, "lote": first // BATCH, "tickets": len(batch)})
    out = run_all(prompts)
    ref = [json.loads(x) for x in out["gpt-fake-large"]]
    summary: dict = {"lotes": len(prompts), "dias": days,
                     "somas_batem_com_tickets_no_large": all(
                         sum(t["count"] for t in r["topics"]) == lab["tickets"] for r, lab in zip(ref, labels))}
    for model in MODELS:
        got = [json.loads(x) for x in out[model]]
        diffs = []
        for i, (a, b) in enumerate(zip(ref, got)):
            if a != b:
                ta = {t["topic"]: t for t in a["topics"]}
                tb = {t["topic"]: t for t in b["topics"]}
                diffs.append({
                    **labels[i],
                    "soma_large": sum(t["count"] for t in a["topics"]),
                    "soma_modelo": sum(t["count"] for t in b["topics"]),
                    "temas_large": len(ta), "temas_modelo": len(tb),
                    "temas_ausentes": sorted(set(ta) - set(tb)),
                    "temas_extras": sorted(set(tb) - set(ta)),
                    "contagens_diferentes": {k: [ta[k]["count"], tb[k]["count"]]
                                             for k in set(ta) & set(tb) if ta[k]["count"] != tb[k]["count"]},
                    "temas_com_exemplos_diferentes": sum(1 for k in set(ta) & set(tb)
                                                         if ta[k]["examples"] != tb[k]["examples"]),
                })
        summary[model] = {"lotes_iguais_ao_gpt_large": len(prompts) - len(diffs),
                          "lotes_diferentes": len(diffs), "detalhes": diffs[:6]}
    return summary


def compare_suggest(sample: list[dict]) -> dict:
    out = run_all([f"TASK: suggest\n{t['text']}" for t in sample])
    ref = out["gpt-fake-large"]
    summary: dict = {"casos": len(sample)}
    for model in MODELS:
        texts = out[model]
        orders = [(ORDER.findall(t["text"]), text) for t, text in zip(sample, texts)]
        summary[model] = {
            "identicos_ao_gpt_large": sum(1 for a, b in zip(ref, texts) if a == b),
            "caracteres_medios": round(sum(len(t) for t in texts) / len(texts)),
            "tickets_com_pedido": sum(1 for found, _ in orders if found),
            "cita_o_numero_do_pedido": sum(1 for found, text in orders if found and all(o in text for o in found)),
            "em_portugues_sem_tarefa_desconhecida": sum(1 for t in texts if "não reconhec" not in t.lower()),
        }
    summary["exemplo_large"] = ref[0][:700]
    summary["exemplo_gpt_mini"] = out["gpt-fake-mini"][0][:700]
    summary["exemplo_claude_mini"] = out["claude-fake-mini"][0][:700]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amostra", type=int, default=1000)
    parser.add_argument("--saida", default="docs/fallback/evidencias/comparacao-modelos.json")
    args = parser.parse_args()

    urllib.request.urlopen(urllib.request.Request(f"{PROVIDER}/admin/reset", method="POST")).read()
    all_tickets = tickets()
    step = max(1, len(all_tickets) // args.amostra)
    sample = all_tickets[::step][:args.amostra]
    started = time.monotonic()
    result = {
        "amostra": f"1 a cada {step} tickets de data/tickets.jsonl ({len(sample)} tickets)",
        "classify": compare_short("classify", sample),
        "extract": compare_short("extract", sample),
        "topics": compare_topics(all_tickets, [f"2026-08-{d:02d}" for d in (1, 2, 5, 9, 13, 17, 21, 25, 29, 31)]),
        "suggest": compare_suggest(sample[:24]),
    }
    result["duracao_s"] = round(time.monotonic() - started, 1)
    urllib.request.urlopen(urllib.request.Request(f"{PROVIDER}/admin/reset", method="POST")).read()
    pathlib.Path(args.saida).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for task in ("classify", "extract", "topics", "suggest"):
        print(task, json.dumps({m: {k: v for k, v in result[task][m].items() if not isinstance(v, (list, dict))}
                                for m in MODELS}, ensure_ascii=False))
    print("duracao_s", result["duracao_s"])


if __name__ == "__main__":
    main()
