import csv

import pytest

from metrics.measure import analyze, main
from metrics.reporting import CSV_HEADER


HELPDESK_LIKE = {
    "helpdesk/__init__.py": "",
    "helpdesk/config.py": "import os\n",
    "helpdesk/schemas.py": "from pydantic import BaseModel\nclass A(BaseModel): ...\nclass B(BaseModel): ...\n",
    "helpdesk/ports/__init__.py": "",
    "helpdesk/ports/llm.py": "from typing import Protocol\nclass LLM(Protocol): ...\n",
    "helpdesk/feature.py": "from . import config\nfrom .schemas import A\nfrom .ports.llm import LLM\n",
    "helpdesk/main.py": "from . import feature\n",
}


def test_cli_gera_csv_exato_e_png(make_package, tmp_path):
    src = make_package(HELPDESK_LIKE)
    out = tmp_path / "results"

    code = main(["--source", str(src), "--name", "teste", "--output-dir", str(out)])

    assert code == 0
    text = (out / "teste.csv").read_text(encoding="utf-8")
    assert text == (
        "component,ca,ce,i,a,d\n"
        "config,1,0,0.00,0.00,1.00\n"
        "feature,1,3,0.75,0.00,0.25\n"
        "main,0,1,1.00,0.00,0.00\n"
        "ports.llm,1,0,0.00,1.00,0.00\n"
        "schemas,1,0,0.00,0.00,1.00\n"
    )
    assert (out / "teste.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cabecalho_quantidade_e_ordem(make_package, tmp_path):
    src = make_package(HELPDESK_LIKE)
    out = tmp_path / "r"
    main(["--source", str(src), "--name", "x", "--output-dir", str(out), "--no-plot"])

    rows = list(csv.reader((out / "x.csv").open(encoding="utf-8")))

    assert rows[0] == CSV_HEADER == ["component", "ca", "ce", "i", "a", "d"]
    names = [r[0] for r in rows[1:]]
    assert names == sorted(names) and len(names) == 5
    assert not (out / "x.png").exists()


def test_medicoes_repetidas_sao_identicas(make_package, tmp_path):
    src = make_package(HELPDESK_LIKE)
    for run in ("a", "b"):
        main(["--source", str(src), "--name", "m", "--output-dir", str(tmp_path / run)])

    assert (tmp_path / "a" / "m.csv").read_bytes() == (tmp_path / "b" / "m.csv").read_bytes()
    assert (tmp_path / "a" / "m.png").read_bytes() == (tmp_path / "b" / "m.png").read_bytes()


def test_valores_exportados_iguais_aos_calculados(make_package, tmp_path):
    src = make_package(HELPDESK_LIKE)
    results, _ = analyze(src)
    main(["--source", str(src), "--name", "v", "--output-dir", str(tmp_path), "--no-plot"])

    rows = {r["component"]: r for r in csv.DictReader((tmp_path / "v.csv").open(encoding="utf-8"))}

    for m in results:
        assert rows[m.component] == {"component": m.component, "ca": str(m.ca), "ce": str(m.ce),
                                     "i": f"{m.i:.2f}", "a": f"{m.a:.2f}", "d": f"{m.d:.2f}"}


def test_erros_de_uso(make_package, tmp_path, capsys):
    src = make_package(HELPDESK_LIKE)

    with pytest.raises(SystemExit) as exc:
        main(["--source", str(tmp_path / "nao-existe"), "--name", "x"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["--source", str(src), "--name", "../fora"])
    assert exc.value.code == 2

    (src / "ruim.py").write_text("class (:\n", encoding="utf-8")
    assert main(["--source", str(src), "--name", "x", "--output-dir", str(tmp_path / "o")]) == 1
    assert not (tmp_path / "o" / "x.csv").exists()
