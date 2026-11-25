import ast
import textwrap

import pytest

from metrics.abstraction import analyze_classes


def abstract_flags(code: str) -> dict[str, bool]:
    return {c.name: c.abstract for c in analyze_classes(ast.parse(textwrap.dedent(code)))}


@pytest.mark.parametrize("code", [
    "from typing import Protocol\nclass P(Protocol): ...",
    "from abc import ABC\nclass P(ABC): ...",
    "import typing\nclass P(typing.Protocol): ...",
    "import abc\nclass P(abc.ABC): ...",
    "from typing import Protocol as Interface\nclass P(Interface): ...",
    "import typing as t\nclass P(t.Protocol): ...",
    "from typing import Protocol, TypeVar\nT = TypeVar('T')\nclass P(Protocol[T]): ...",
    "import typing\nT = typing.TypeVar('T')\nclass P(typing.Protocol[T]): ...",
    "from abc import ABC\nclass Base: ...\nclass P(Base, ABC): ...",
], ids=["protocol", "abc", "typing-qualificado", "abc-qualificado", "alias-simbolo",
        "alias-modulo", "protocol-parametrizado", "protocol-parametrizado-qualificado", "multiplas-bases"])
def test_classes_abstratas_validas(code):
    assert abstract_flags(code)["P"] is True


@pytest.mark.parametrize("code", [
    "class P: ...",
    "from pydantic import BaseModel\nclass P(BaseModel): ...",
    "class Protocol: ...\nclass P(Protocol): ...",                     # Protocol local
    "class ABC: ...\nclass P(ABC): ...",                               # ABC local
    "from .ports import Protocol\nclass P(Protocol): ...",             # outro módulo
    "from mylib import ABC\nclass P(ABC): ...",
    "from typing_extensions import Protocol\nclass P(Protocol): ...",  # fora da régua
    "from abc import ABCMeta\nclass P(metaclass=ABCMeta): ...",        # fora da régua
    "from typing import Generic, TypeVar\nT = TypeVar('T')\nclass P(Generic[T]): ...",
    "from abc import ABC\nclass Base(ABC): ...\nclass P(Base): ...",   # herança indireta
    "import abc\nclass P(abc.ABCMeta): ...",
], ids=["concreta", "pydantic", "protocol-local", "abc-local", "relativo", "externo",
        "typing-extensions", "metaclass", "generic", "indireta", "abcmeta"])
def test_classes_que_nao_contam_como_abstratas(code):
    assert abstract_flags(code)["P"] is False


def test_modulo_sem_classes():
    assert analyze_classes(ast.parse("import os\nX = 1\ndef f(): ...")) == []


def test_abstratas_e_concretas_no_mesmo_modulo_inclusive_aninhadas():
    classes = analyze_classes(ast.parse(textwrap.dedent("""
        from typing import Protocol
        from abc import ABC
        class Port(Protocol): ...
        class Base(ABC): ...
        class Impl:
            class Inner(Protocol): ...
        def factory():
            class Local: ...
    """)))

    assert [(c.name, c.abstract) for c in classes] == [
        ("Port", True), ("Base", True), ("Impl", False), ("Inner", True), ("Local", False)]


def test_nome_reimportado_depois_volta_a_valer():
    flags = abstract_flags("""
        class Protocol: ...
        class A(Protocol): ...
        from typing import Protocol
        class B(Protocol): ...
    """)

    assert flags == {"Protocol": False, "A": False, "B": True}
