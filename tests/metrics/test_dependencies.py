import pytest

from metrics.dependencies import build_graph
from metrics.discovery import discover_components
from metrics.parsing import AnalysisError
from metrics.measure import analyze


def edges_of(src, root="helpdesk"):
    graph = build_graph(src, discover_components(src), root)
    return graph, {c: sorted(t) for c, t in graph.out_edges.items()}


BASE = {"helpdesk/__init__.py": "", "helpdesk/config.py": "X = 1\n"}


@pytest.mark.parametrize("statement", [
    "import helpdesk.config",
    "import helpdesk.config as configuration",
    "from helpdesk import config",
    "from helpdesk.config import X",
    "from helpdesk.config import X as Y",
    "from . import config",
    "from .config import X",
], ids=["import-abs", "import-alias", "from-pacote", "from-simbolo", "from-simbolo-alias",
        "relativo-modulo", "relativo-simbolo"])
def test_cada_forma_de_import_resolve_para_o_modulo(make_package, statement):
    src = make_package({**BASE, "helpdesk/a.py": statement + "\n"})

    _, out = edges_of(src)

    assert out["a"] == ["config"]   # nunca "config.X"


def test_imports_repetidos_contam_uma_vez(make_package):
    src = make_package({**BASE, "helpdesk/a.py": """
        import helpdesk.config
        from helpdesk import config
        from .config import X
        from . import config as c

        def f():
            from helpdesk.config import X
    """})

    graph, out = edges_of(src)

    assert out["a"] == ["config"]
    assert len(graph.in_edges["config"]) == 1


def test_externos_e_biblioteca_padrao_sao_ignorados(make_package):
    src = make_package({**BASE, "helpdesk/a.py": """
        import os, json
        from datetime import date
        from fastapi import FastAPI
        import openai
        from pydantic import BaseModel
        import config          # sem o pacote raiz: absoluto de fora da árvore
    """})

    _, out = edges_of(src)

    assert out["a"] == []


def test_subpacotes_relativos_e_absolutos(make_package):
    src = make_package({
        "helpdesk/__init__.py": "",
        "helpdesk/ports/__init__.py": "from .llm import LLMPort\n",
        "helpdesk/ports/llm.py": "class LLMPort: ...\n",
        "helpdesk/adapters/__init__.py": "",
        "helpdesk/adapters/gateway.py": """
            from ..ports.llm import LLMPort
            from ..ports import llm
        """,
        "helpdesk/adapters/other.py": "from . import gateway\nfrom .gateway import x\n",
        "helpdesk/features/f.py": """
            from helpdesk.adapters import gateway
            from ..ports import LLMPort        # símbolo reexportado pelo __init__
        """,
    })

    _, out = edges_of(src)

    assert out["adapters.gateway"] == ["ports.llm"]
    assert out["adapters.other"] == ["adapters.gateway"]
    assert out["features.f"] == ["adapters.gateway", "ports.llm"]
    assert out["ports.llm"] == []


def test_init_nao_vira_componente_nem_aresta(make_package):
    src = make_package({
        "helpdesk/__init__.py": "from .config import X\n",
        "helpdesk/config.py": "X = 1\n",
        "helpdesk/a.py": "import helpdesk\nfrom helpdesk import X\n",
    })

    graph, out = edges_of(src)

    assert "__init__" not in graph.nodes
    assert out["a"] == ["config"]        # X é reexportado: depende de config


def test_ciclo_autorreferencia_e_isolado(make_package):
    src = make_package({
        "helpdesk/__init__.py": "",
        "helpdesk/a.py": "from . import b\nfrom . import a\nimport helpdesk.a\n",
        "helpdesk/b.py": "from .a import thing\n",
        "helpdesk/solo.py": "import os\n",
    })

    graph, out = edges_of(src)

    assert out == {"a": ["b"], "b": ["a"], "solo": []}
    assert graph.in_edges["solo"] == set()


def test_dependencia_transitiva_nao_vira_direta(make_package):
    src = make_package({
        "helpdesk/__init__.py": "",
        "helpdesk/a.py": "from . import b\n",
        "helpdesk/b.py": "from . import c\n",
        "helpdesk/c.py": "",
    })

    _, out = edges_of(src)

    assert out["a"] == ["b"]


def test_import_em_bloco_condicional_e_contado(make_package):
    src = make_package({**BASE, "helpdesk/a.py": """
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from .config import X
    """})

    _, out = edges_of(src)

    assert out["a"] == ["config"]


def test_import_interno_inexistente_e_reportado(make_package):
    src = make_package({**BASE, "helpdesk/a.py": "from .nao_existe import y\nfrom . import fantasma\n"})

    graph, out = edges_of(src)

    assert out["a"] == []
    assert len(graph.unresolved) == 2


def test_soma_de_ca_igual_soma_de_ce(make_package):
    src = make_package({
        "helpdesk/__init__.py": "",
        "helpdesk/a.py": "from . import b, c\n",
        "helpdesk/b.py": "from . import c\n",
        "helpdesk/c.py": "from . import a\n",
    })

    graph, _ = edges_of(src)

    assert sum(len(v) for v in graph.in_edges.values()) == sum(len(v) for v in graph.out_edges.values()) == 4


def test_erro_de_sintaxe_aborta_a_medicao(make_package):
    src = make_package({**BASE, "helpdesk/quebrado.py": "def f(:\n"})

    with pytest.raises(AnalysisError, match="quebrado.py"):
        analyze(src)


def test_analise_nao_executa_o_codigo(make_package, tmp_path):
    marker = tmp_path / "executou.txt"
    src = make_package({**BASE, "helpdesk/a.py": f"""
        from pathlib import Path
        Path({str(marker)!r}).write_text("sim")
        from . import config
    """})

    results, _ = analyze(src)

    assert not marker.exists()
    assert {m.component: m.ce for m in results}["a"] == 1
