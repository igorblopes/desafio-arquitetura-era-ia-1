"""Exemplo didático do Passo 13: `def`, `async def` bloqueante e `async def` não bloqueante.

Não usa a app do helpdesk nem o provider: sobe um FastAPI mínimo em processo (uvicorn numa
thread) com três rotas que "esperam um modelo" por 1 s, e dispara N requisições simultâneas
em cada uma. O que muda é SÓ o modelo de execução da espera:

  /def-bloqueante          def        + time.sleep(1)       -> roda no thread pool (40 threads)
  /async-bloqueante        async def  + time.sleep(1)       -> roda NO event loop e o congela
  /async-nao-bloqueante    async def  + await asyncio.sleep -> devolve o loop enquanto espera

As três são Request-Response síncronas para o cliente: ele espera a resposta completa.

    python docs/execucao/exemplo_event_loop.py [N]    # N padrão 10; requer fastapi, uvicorn, httpx
"""

import asyncio
import json
import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

app = FastAPI()
WAIT = 1.0


@app.get("/def-bloqueante")
def def_blocking():
    time.sleep(WAIT)  # bloqueia só a thread do pool que atende esta requisição
    return {"ok": True}


@app.get("/async-bloqueante")
async def async_blocking():
    time.sleep(WAIT)  # ERRO comum: bloqueia o event loop inteiro (todas as requisições)
    return {"ok": True}


@app.get("/async-nao-bloqueante")
async def async_non_blocking():
    await asyncio.sleep(WAIT)  # suspende a coroutine; o loop atende as outras
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}


def burst(path: str, n: int) -> dict:
    """N requisições simultâneas na rota + 1 /health disparado 0,2 s depois."""
    results: list[float] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n + 1)

    def worker() -> None:
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=60) as c:
            barrier.wait()
            t0 = time.perf_counter()
            c.get(path)
            with lock:
                results.append(time.perf_counter() - t0)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    barrier.wait()
    start = time.perf_counter()
    time.sleep(0.2)
    t0 = time.perf_counter()
    httpx.get("http://127.0.0.1:8765/health", timeout=60)
    health = time.perf_counter() - t0
    for t in threads:
        t.join()
    return {"rota": path, "simultaneas": n, "conjunto_s": round(time.perf_counter() - start, 2),
            "latencia_min_s": round(min(results), 2), "latencia_max_s": round(max(results), 2),
            "health_durante_s": round(health, 3)}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    rows = [burst(p, n) for p in ("/def-bloqueante", "/async-bloqueante", "/async-nao-bloqueante")]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    server.should_exit = True


if __name__ == "__main__":
    main()
