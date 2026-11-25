from metrics.discovery import discover_components


def test_descobre_recursivamente_exclui_init_e_usa_pontos(make_package):
    src = make_package({
        "helpdesk/__init__.py": "",
        "helpdesk/main.py": "",
        "helpdesk/config.py": "",
        "helpdesk/adapters/__init__.py": "",
        "helpdesk/adapters/gateway.py": "",
        "helpdesk/ports/llm.py": "",          # subpacote sem __init__ também conta
        "helpdesk/notes.txt": "não é python",
    })

    found = discover_components(src)

    assert list(found) == ["adapters.gateway", "config", "main", "ports.llm"]
    assert found["adapters.gateway"] == src / "adapters" / "gateway.py"


def test_ordem_deterministica_independe_da_criacao(make_package):
    src = make_package({"helpdesk/z.py": "", "helpdesk/a.py": "", "helpdesk/m/b.py": ""})

    assert list(discover_components(src)) == ["a", "m.b", "z"]


def test_diretorio_sem_modulos(make_package):
    src = make_package({"helpdesk/__init__.py": ""})

    assert discover_components(src) == {}
