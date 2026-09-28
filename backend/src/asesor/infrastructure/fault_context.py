from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from asesor.agent.guardrails.faults import Fault

# Request-scoped: the X-Debug-Fault header reaches the router, but the model
# and the tools run several layers below. A contextvar reaches them without
# cluttering ADK's signatures, and it's isolated per turn (matters with
# concurrent sessions).
_active_fault: ContextVar[Fault | None] = ContextVar("active_fault", default=None)


@contextmanager
def use_fault(fault: Fault | None) -> Iterator[None]:
    token = _active_fault.set(fault)
    try:
        yield
    finally:
        _active_fault.reset(token)


def current_fault() -> Fault | None:
    return _active_fault.get()
