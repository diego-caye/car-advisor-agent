from pathlib import Path

import pytest

from asesor.domain.enums import KbCategory
from asesor.infrastructure.kb_loader import (
    KbFormatError,
    load_chunks,
    parse_document,
    split_by_headings,
)

KB_DIR = Path(__file__).parents[3] / "kb"


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parsea_frontmatter(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "doc.md",
        '---\ntitle: "Un título"\ncategoria: FUEL_ECONOMY\n---\n\n## Sección\n\nTexto.\n',
    )

    document = parse_document(path)

    assert document.title == "Un título"
    assert document.category is KbCategory.FUEL_ECONOMY
    assert document.source == "doc.md"
    assert document.body.startswith("## Sección")


def test_rechaza_documento_sin_frontmatter(tmp_path: Path) -> None:
    path = write(tmp_path, "doc.md", "# Sin frontmatter\n")

    with pytest.raises(KbFormatError, match="frontmatter"):
        parse_document(path)


def test_rechaza_categoria_invalida(tmp_path: Path) -> None:
    path = write(tmp_path, "doc.md", "---\ntitle: X\ncategoria: INVENTADA\n---\n\ntexto\n")

    with pytest.raises(KbFormatError, match="categoria"):
        parse_document(path)


def test_trocea_por_encabezados_de_nivel_dos() -> None:
    body = "## Uno\n\n" + "a " * 300 + "\n\n## Dos\n\n" + "b " * 300

    chunks = split_by_headings(body)

    assert len(chunks) == 2
    assert chunks[0].startswith("## Uno")
    assert chunks[1].startswith("## Dos")


def test_une_secciones_demasiado_cortas() -> None:
    body = "## Uno\n\ncorto\n\n## Dos\n\ntambién corto"

    chunks = split_by_headings(body)

    assert len(chunks) == 1
    assert "## Uno" in chunks[0] and "## Dos" in chunks[0]


def test_parte_secciones_demasiado_largas() -> None:
    body = "## Larga\n\n" + "palabra " * 2000

    chunks = split_by_headings(body)

    assert len(chunks) > 1
    assert all(len(chunk) <= 2800 for chunk in chunks)


def test_la_kb_real_carga_y_los_hashes_son_estables() -> None:
    first = load_chunks(KB_DIR)
    second = load_chunks(KB_DIR)

    assert len(first) >= 15
    assert [chunk.content_hash for chunk in first] == [chunk.content_hash for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)


def test_la_kb_real_no_menciona_precios_ni_marcas() -> None:
    prohibidos = ["S/.", "USD", "$", "precio de lista", "cuota mensual"]

    for chunk in load_chunks(KB_DIR):
        for termino in prohibidos:
            assert termino not in chunk.content, f"{chunk.source} menciona '{termino}'"
