import json, os, time, statistics, urllib.request, urllib.error

BASE = "http://provider-fake:8090"
OK = os.environ["FAKE_OPENAI_KEY"]
AK = os.environ["FAKE_ANTHROPIC_KEY"]
MODELS = [("openai", "gpt-fake-large"), ("openai", "gpt-fake-mini"),
          ("anthropic", "claude-fake-large"), ("anthropic", "claude-fake-mini")]
PRICE = {"gpt-fake-large": (2.50, 10.00), "gpt-fake-mini": (0.15, 0.60),
         "claude-fake-large": (3.00, 15.00), "claude-fake-mini": (0.80, 4.00)}


def cost(model, i, o):
    pi, po = PRICE[model]
    return round(((i or 0) * pi + (o or 0) * po) / 1e6, 8)


def call(provider, model, content, stream=False, max_tokens=2000):
    if provider == "openai":
        url = BASE + "/openai/v1/chat/completions"
        hdr = {"Authorization": "Bearer " + OK}
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
    else:
        url = BASE + "/anthropic/v1/messages"
        hdr = {"x-api-key": AK, "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
    if stream:
        body["stream"] = True
    hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr, method="POST")
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(req, timeout=400)
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:300], "total_s": round(time.monotonic() - t0, 3)}
    th = time.monotonic() - t0
    if not stream:
        d = json.loads(r.read())
        tt = time.monotonic() - t0
        if provider == "openai":
            text = d["choices"][0]["message"]["content"]
            i, o = d["usage"]["prompt_tokens"], d["usage"]["completion_tokens"]
            fin = d["choices"][0]["finish_reason"]
        else:
            text = d["content"][0]["text"]
            i, o = d["usage"]["input_tokens"], d["usage"]["output_tokens"]
            fin = d["stop_reason"]
        return {"status": r.status, "ttfb_s": round(th, 3), "total_s": round(tt, 3), "text": text,
                "in": i, "out": o, "finish": fin, "cost": cost(model, i, o)}
    first, parts, usage_in, usage_out, fin = None, [], None, None, None
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        ev = json.loads(p)
        piece = None
        if provider == "openai":
            ch = ev.get("choices") or []
            if ch:
                piece = ch[0].get("delta", {}).get("content")
                fin = ch[0].get("finish_reason") or fin
        else:
            t = ev.get("type")
            if t == "message_start":
                usage_in = ev["message"]["usage"].get("input_tokens")
            if t == "content_block_delta":
                piece = ev["delta"].get("text")
            if t == "message_delta":
                usage_out = ev.get("usage", {}).get("output_tokens")
                fin = ev["delta"].get("stop_reason")
        if piece:
            if first is None:
                first = time.monotonic() - t0
            parts.append(piece)
    tt = time.monotonic() - t0
    return {"status": r.status, "ttfb_s": round(th, 3), "first_content_s": round(first, 3) if first else None,
            "total_s": round(tt, 3), "chunks": len(parts), "chars": len("".join(parts)),
            "in": usage_in, "out": usage_out, "finish": fin, "text": "".join(parts)}


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"n": len(xs), "min": min(xs), "max": max(xs), "mean": round(statistics.mean(xs), 3),
            "median": round(statistics.median(xs), 3), "range": round(max(xs) - min(xs), 3)}


def admin(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    return json.loads(urllib.request.urlopen(req).read())


def parse(text):
    try:
        return json.loads(text)
    except Exception:
        return {"_invalid_json": text[:200]}


tickets = [json.loads(l) for l in open("/data/tickets.jsonl", encoding="utf-8")]
OUT = {}
admin("/admin/reset", "POST")
OUT["failures"] = admin("/admin/failures")

# ---------- F1 classify ----------
F1 = [
    ("c01", "Meu pedido #481516 não chegou e já passou do prazo, urgente", "delivery", "high"),
    ("c02", "Fui cobrado duas vezes no cartão pela mesma compra", "payment", None),
    ("c03", "Quero trocar a camiseta básica por um tamanho maior, sem pressa", "exchange_return", "low"),
    ("c04", "O liquidificador chegou quebrado e não liga", "product_defect", None),
    ("c05", "Como faço para alterar meu e-mail de cadastro?", "other", "low"),
    ("c06", "O boleto venceu e não consigo pagar, preciso resolver hoje", "payment", "high"),
    ("c07", "A entrega está atrasada há dois dias", "delivery", None),
    ("c08", "Quero devolver o tênis de corrida, me arrependi da compra", "exchange_return", None),
    ("c09", "URGENTE: meu smartwatch parou de funcionar depois de uma semana", "product_defect", "high"),
    ("c10", "Recebi a cafeteira elétrica danificada e quero trocar por outra", None, None),
    ("c11", "Estou muito irritado, ninguém responde, o pix foi cobrado e o pedido não saiu", None, "high"),
]
for t in tickets[:10]:
    F1.append((t["id"], t["text"], None, None))
OUT["F1"] = []
for cid, text, ecat, epri in F1:
    row = {"case": cid, "text": text, "expected": {"category": ecat, "priority": epri}, "models": {}}
    for p, m in MODELS:
        r = call(p, m, "TASK: classify\n" + text)
        r["parsed"] = parse(r.get("text", "{}"))
        r.pop("text", None)
        row["models"][m] = r
    OUT["F1"].append(row)
# determinism / latency repetitions
OUT["F1_reps"] = {}
for p, m in MODELS:
    runs = [call(p, m, "TASK: classify\n" + F1[0][1]) for _ in range(3)]
    OUT["F1_reps"][m] = {"total": stats([x["total_s"] for x in runs]),
                         "identical": len({x["text"] for x in runs}) == 1}

# ---------- F4 extract ----------
F4 = [
    ("e01", "Pedido #481516, o fone de ouvido bluetooth veio com chiado", "#481516", "fone de ouvido bluetooth"),
    ("e02", "Quero trocar a calça jeans do pedido #605065 por outro tamanho", "#605065", "calça jeans"),
    ("e03", "Como faço para alterar meu e-mail de cadastro?", None, None),
    ("e04", "Meu pedido 481516 não chegou", "ambiguo(#481516 ou null)", None),
    ("e05", "O protocolo #12345 não resolveu, o aspirador robô continua sem funcionar", None, "aspirador robô"),
    ("e06", "Comprei a air fryer no pedido #112233 e a cafeteira elétrica no pedido #445566; só a cafeteira veio quebrada", "#445566", "cafeteira elétrica"),
    ("e07", "Paguei 1234567 reais por engano? Pedido #998877, smartwatch", "#998877", "smartwatch"),
    ("e08", "CPF 123.456.789-00, pedido #314159 do mouse sem fio", "#314159", "mouse sem fio"),
    ("e09", "Quero devolver o tênis Runner Pro do pedido #123456", "#123456", "tênis Runner Pro"),
    ("e10", "O pedido #4815162 veio com o produto errado", None, None),
    ("e11", "Quero trocar o produto, chegou com defeito", None, None),
    ("e12", "O pedido #777888 chegou, mas a power bank não carrega", "#777888", "power bank"),
]
OUT["F4"] = []
for cid, text, eord, eprod in F4:
    row = {"case": cid, "text": text, "expected": {"order_number": eord, "product": eprod}, "models": {}}
    for p, m in MODELS:
        r = call(p, m, "TASK: extract\n" + text)
        r["parsed"] = parse(r.get("text", "{}"))
        r.pop("text", None)
        row["models"][m] = r
    OUT["F4"].append(row)

# ---------- F2 suggest ----------
F2 = [("s01", F1[0][1]), ("s02", F1[1][1]), ("s03", F1[3][1])]
OUT["F2_sync"] = []
for cid, text in F2:
    row = {"case": cid, "models": {}}
    for p, m in MODELS:
        r = call(p, m, "TASK: suggest\n" + text)
        r["text_head"] = r.get("text", "")[:400]
        r["chars"] = len(r.get("text", ""))
        r["text_sha"] = hash(r.pop("text", ""))
        row["models"][m] = r
    OUT["F2_sync"].append(row)
OUT["F2_stream"] = {}
for p, m in MODELS:
    runs = [call(p, m, "TASK: suggest\n" + F2[0][1], stream=True) for _ in range(3)]
    OUT["F2_stream"][m] = {"ttfb": stats([x["ttfb_s"] for x in runs]),
                           "first_content": stats([x["first_content_s"] for x in runs]),
                           "total": stats([x["total_s"] for x in runs]),
                           "chunks": runs[0]["chunks"], "chars": runs[0]["chars"],
                           "in": runs[0]["in"], "out": runs[0]["out"], "finish": runs[0]["finish"]}
for p, m in MODELS:
    a = call(p, m, "TASK: suggest\n" + F2[0][1], max_tokens=50)
    OUT.setdefault("F2_maxtokens50", {})[m] = {k: a.get(k) for k in ("status", "out", "finish", "total_s")}

# ---------- F3 topics ----------
day1 = [t for t in tickets if t["created_at"].startswith("2026-08-01")]
SETS = {"first20": tickets[:20], "first150": tickets[:150], "day1_137": day1, "first200": tickets[:200]}
OUT["F3"] = {}
for name, batch in SETS.items():
    content = "\n".join(f"[{t['id']}] {t['text']}" for t in batch)
    row = {"n_tickets": len(batch), "chars": len(content), "models": {}}
    for p, m in MODELS:
        r = call(p, m, "TASK: topics\n" + content)
        if r.get("status") == 200:
            d = parse(r.pop("text"))
            topics = d.get("topics", [])
            r["n_topics"] = len(topics)
            r["sum_counts"] = sum(x.get("count", 0) for x in topics)
            r["topics"] = topics
            ids = {t["id"] for t in batch}
            r["examples_not_in_input"] = [e for x in topics for e in x.get("examples", []) if e not in ids]
        row["models"][m] = r
    OUT["F3"][name] = row

calls = admin("/admin/calls?last=5000")
summary = {}
for c in calls:
    k = f'{c["provider"]}|{c["model"]}|{c["task"]}|stream={c["stream"]}|{c["status"]}'
    s = summary.setdefault(k, {"n": 0, "in": 0, "out": 0, "ms": 0})
    s["n"] += 1
    s["in"] += c["input_tokens"] or 0
    s["out"] += c["output_tokens"] or 0
    s["ms"] += c["duration_ms"] or 0
OUT["admin_calls_total"] = len(calls)
OUT["admin_calls_summary"] = summary
admin("/admin/reset", "POST")
OUT["failures_after"] = admin("/admin/failures")
print(json.dumps(OUT, ensure_ascii=False))
