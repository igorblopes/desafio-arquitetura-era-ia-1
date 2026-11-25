"""Testes da ferramenta de métricas, com pacotes Python artificiais.

Cada teste cria uma árvore pequena em tmp_path; nada do app/ real é usado
nem alterado.
"""

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def make_package(tmp_path):
    """make_package({"helpdesk/a.py": "...", ...}) -> Path de helpdesk/."""
    def _make(files: dict[str, str], root: str = "helpdesk") -> Path:
        for rel, content in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content), encoding="utf-8")
        return tmp_path / root
    return _make
