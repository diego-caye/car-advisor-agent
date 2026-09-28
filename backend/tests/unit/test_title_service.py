from uuid import uuid4

import pytest

from asesor.application.title_service import TitleService, clean_title, fallback_title
from asesor.infrastructure.llm.fake import FakeAdkLlm, FakeTurn


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("SUV para la familia", "SUV para la familia"),
        ('"SUV para la familia"', "SUV para la familia"),
        ("Título: Comparar híbridos", "Comparar híbridos"),
        ("title: Test drive el sábado", "Test drive el sábado"),
        ("Consulta sobre GNV\n\nEspero que ayude.", "Consulta sobre GNV"),
        ("  Consumo   en   ciudad  ", "Consumo en ciudad"),
        ("Mantenimiento básico.", "Mantenimiento básico"),
    ],
)
def test_limpia_lo_que_anaden_los_modelos_pequenos(crudo: str, esperado: str) -> None:
    assert clean_title(crudo) == esperado


def test_recorta_titulos_demasiado_largos() -> None:
    assert len(clean_title("palabra " * 40)) <= 48


def test_sin_respuesta_usable_el_titulo_sale_del_mensaje() -> None:
    assert fallback_title("  quiero  una SUV ") == "quiero una SUV"


def test_el_mensaje_largo_se_recorta_con_puntos_suspensivos() -> None:
    titulo = fallback_title("necesito un auto " * 10)

    assert len(titulo) <= 48
    assert titulo.endswith("…")


class _FakeTitleRepo:
    """The same contract as SqlSessionTitleRepository, in memory: these tests
    are about ensure_title's logic (generates once, doesn't race for
    anything), not about SQL — that's already covered by
    test_session_title_repository.py.
    """

    def __init__(self) -> None:
        self.titles: dict[str, str] = {}

    async def get(self, session_id: str) -> str | None:
        return self.titles.get(session_id)

    async def upsert(self, session_id: str, user_id: object, title: str) -> None:
        self.titles[session_id] = title


async def test_ensure_title_genera_y_guarda_cuando_no_hay_ninguno() -> None:
    model = FakeAdkLlm(turns=[FakeTurn(text="SUV para la familia")])
    repo = _FakeTitleRepo()
    service = TitleService(model, repo)  # type: ignore[arg-type]

    titulo = await service.ensure_title(uuid4(), "sesion-1", "busco un SUV para mi familia")

    assert titulo == "SUV para la familia"
    assert repo.titles["sesion-1"] == "SUV para la familia"


async def test_ensure_title_no_hace_nada_si_ya_hay_titulo() -> None:
    model = FakeAdkLlm(turns=[FakeTurn(text="esto no debería usarse")])
    repo = _FakeTitleRepo()
    repo.titles["sesion-1"] = "titulo existente"
    service = TitleService(model, repo)  # type: ignore[arg-type]

    titulo = await service.ensure_title(uuid4(), "sesion-1", "otro mensaje")

    assert titulo is None
    assert model.calls == 0
    assert repo.titles["sesion-1"] == "titulo existente"


async def test_ensure_title_cae_al_mensaje_si_el_modelo_no_da_nada_usable() -> None:
    model = FakeAdkLlm(turns=[FakeTurn(text="")])
    repo = _FakeTitleRepo()
    service = TitleService(model, repo)  # type: ignore[arg-type]

    titulo = await service.ensure_title(uuid4(), "sesion-1", "hola")

    assert titulo == "hola"
    assert repo.titles["sesion-1"] == "hola"
