from asesor.domain.entities import Lead
from asesor.domain.enums import InterestLevel, Stage

_FORWARD_ORDER: tuple[Stage, ...] = (
    Stage.NEW,
    Stage.DISCOVERY,
    Stage.CONCRETE_INTEREST,
    Stage.HANDOFF_PENDING,
    Stage.HANDED_OFF,
)

_HITL_STAGES = frozenset({Stage.HANDOFF_PENDING, Stage.HANDED_OFF})


def has_concrete_interest(lead: Lead) -> bool:
    if lead.interest_level is InterestLevel.HIGH:
        return True
    knows_vehicle = lead.vehicle_type_interest is not None or lead.powertrain_interest is not None
    return lead.primary_use is not None and knows_vehicle


def stage_from_lead(lead: Lead) -> Stage:
    if has_concrete_interest(lead):
        return Stage.CONCRETE_INTEREST
    if lead.name:
        return Stage.DISCOVERY
    return Stage.NEW


def next_stage(current: Stage, lead: Lead) -> Stage:
    if current in _HITL_STAGES:
        return current

    derived = stage_from_lead(lead)
    if _FORWARD_ORDER.index(derived) > _FORWARD_ORDER.index(current):
        return derived
    return current
