from collections.abc import Mapping
from typing import Any

from google.adk.sessions.state import State

from asesor.domain.entities import DialogState
from asesor.domain.enums import Stage

STAGE_KEY = "stage"
SOLO_MIRANDO_KEY = "just_browsing"
STAGE_PREVIA_KEY = "previous_stage"

# ADK's State is not a Mapping, so the union covers it plus dict/MappingProxyType.
StateLike = State | Mapping[str, Any]


def read_dialog_state(state: StateLike) -> DialogState:
    raw_stage = state.get(STAGE_KEY)
    raw_previa = state.get(STAGE_PREVIA_KEY)
    return DialogState(
        stage=Stage(raw_stage) if raw_stage else Stage.NEW,
        just_browsing=bool(state.get(SOLO_MIRANDO_KEY, False)),
        previous_stage=Stage(raw_previa) if raw_previa else None,
    )


def stage_delta(stage: Stage) -> dict[str, Any]:
    return {STAGE_KEY: stage.value}
