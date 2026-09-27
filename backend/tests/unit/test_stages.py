from uuid import uuid4

import pytest

from asesor.domain.entities import Lead
from asesor.domain.enums import InterestLevel, Powertrain, PrimaryUse, Stage, VehicleType
from asesor.domain.stages import next_stage, stage_from_lead

USER = uuid4()


def lead(**kwargs: object) -> Lead:
    return Lead(user_id=USER, **kwargs)  # type: ignore[arg-type]


def test_empty_lead_stays_nuevo() -> None:
    assert stage_from_lead(lead()) is Stage.NEW


def test_name_moves_to_descubrimiento() -> None:
    assert next_stage(Stage.NEW, lead(name="Diego")) is Stage.DISCOVERY


def test_use_plus_vehicle_type_moves_to_interes_concreto() -> None:
    current = lead(
        name="Diego",
        primary_use=PrimaryUse.FAMILY,
        vehicle_type_interest=VehicleType.SUV,
    )
    assert next_stage(Stage.DISCOVERY, current) is Stage.CONCRETE_INTEREST


def test_use_plus_motorizacion_also_moves_to_interes_concreto() -> None:
    current = lead(
        name="Diego",
        primary_use=PrimaryUse.CITY,
        powertrain_interest=Powertrain.HYBRID,
    )
    assert next_stage(Stage.DISCOVERY, current) is Stage.CONCRETE_INTEREST


def test_use_alone_is_not_enough() -> None:
    current = lead(name="Diego", primary_use=PrimaryUse.CITY)
    assert next_stage(Stage.DISCOVERY, current) is Stage.DISCOVERY


def test_high_interest_alone_moves_to_interes_concreto() -> None:
    current = lead(name="Diego", interest_level=InterestLevel.HIGH)
    assert next_stage(Stage.DISCOVERY, current) is Stage.CONCRETE_INTEREST


def test_machine_only_moves_forward() -> None:
    assert next_stage(Stage.CONCRETE_INTEREST, lead()) is Stage.CONCRETE_INTEREST
    assert next_stage(Stage.DISCOVERY, lead()) is Stage.DISCOVERY


def test_machine_may_skip_descubrimiento() -> None:
    anonymous_but_decided = lead(
        primary_use=PrimaryUse.WORK,
        vehicle_type_interest=VehicleType.PICKUP,
    )
    assert next_stage(Stage.NEW, anonymous_but_decided) is Stage.CONCRETE_INTEREST


@pytest.mark.parametrize("stage", [Stage.HANDOFF_PENDING, Stage.HANDED_OFF])
def test_hitl_stages_are_never_recomputed_from_the_lead(stage: Stage) -> None:
    rich = lead(name="Diego", interest_level=InterestLevel.HIGH)
    assert next_stage(stage, rich) is stage
