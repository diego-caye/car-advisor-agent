from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from google.adk.tools import ToolContext
from pydantic import BaseModel, ValidationError

from asesor.agent.state import SOLO_MIRANDO_KEY, STAGE_KEY, read_dialog_state
from asesor.agent.tools.envelope import error, ok
from asesor.application.lead_service import LeadService
from asesor.domain.entities import LeadUpdate
from asesor.domain.enums import (
    CanalPreferido,
    Motorizacion,
    NivelInteres,
    TipoVehiculo,
    UsoPrincipal,
)
from asesor.domain.errors import DomainError

GuardarLead = Callable[..., Awaitable[dict[str, Any]]]


class _GuardarLeadArgs(BaseModel):
    nombre: str | None = None
    telefono: str | None = None
    email: str | None = None
    canal_preferido: CanalPreferido | None = None
    consentimiento_contacto: bool | None = None
    uso_principal: UsoPrincipal | None = None
    tipo_vehiculo_interes: TipoVehiculo | None = None
    motorizacion_interes: Motorizacion | None = None
    nivel_interes: NivelInteres | None = None
    solo_mirando: bool | None = None

    def to_update(self) -> LeadUpdate:
        return LeadUpdate(**self.model_dump(exclude={"solo_mirando"}))


def make_guardar_lead(lead_service: LeadService) -> GuardarLead:
    async def guardar_lead(
        tool_context: ToolContext,
        nombre: str | None = None,
        telefono: str | None = None,
        email: str | None = None,
        canal_preferido: str | None = None,
        consentimiento_contacto: bool | None = None,
        uso_principal: str | None = None,
        tipo_vehiculo_interes: str | None = None,
        motorizacion_interes: str | None = None,
        nivel_interes: str | None = None,
        solo_mirando: bool | None = None,
    ) -> dict[str, Any]:
        """Guarda o actualiza la ficha del usuario con los datos que vaya compartiendo.

        Llámala apenas el usuario dé su nombre, su uso principal, el tipo de vehículo o
        la motorización que le interesa, o cuando notes que cambió su nivel de interés.
        Actualiza solo los campos que conozcas: manda null en todos los demás.

        Args:
            nombre: Nombre del usuario, 1 a 80 caracteres.
            telefono: Celular peruano de 9 dígitos o número en formato internacional.
            email: Correo electrónico del usuario.
            canal_preferido: Uno de WHATSAPP, LLAMADA, EMAIL, CHAT.
            consentimiento_contacto: true si el usuario aceptó explícitamente ser
                contactado. Obligatorio si mandas telefono o email.
            uso_principal: Uno de CIUDAD, TRABAJO, FAMILIA, VIAJES, MIXTO.
            tipo_vehiculo_interes: Uno de SUV, SEDAN, HATCHBACK, PICKUP, VAN,
                CROSSOVER, OTRO.
            motorizacion_interes: Uno de GASOLINA, DIESEL, HIBRIDO, ELECTRICO,
                GLP_GNV, NO_DEFINIDO.
            nivel_interes: Uno de BAJO, MEDIO, ALTO, deducido de la conversación.
            solo_mirando: true la primera vez que el usuario diga que solo está
                mirando/comparando, sin intención de avanzar todavía. Puede ir solo,
                sin ningún otro campo. Una vez activado, sigue así el resto de la
                conversación: no hace falta volver a mandarlo.

        Returns:
            La ficha actualizada y la etapa del diálogo.
        """
        try:
            args = _GuardarLeadArgs(
                nombre=nombre,
                telefono=telefono,
                email=email,
                canal_preferido=canal_preferido,
                consentimiento_contacto=consentimiento_contacto,
                uso_principal=uso_principal,
                tipo_vehiculo_interes=tipo_vehiculo_interes,
                motorizacion_interes=motorizacion_interes,
                nivel_interes=nivel_interes,
                solo_mirando=solo_mirando,
            )
        except ValidationError as exc:
            return error("VALIDATION_ERROR", _first_message(exc))

        if args.solo_mirando:
            # Lives in the session state (dialog state), not in the user's
            # record: it's an intent for this conversation, not a lead field.
            tool_context.state[SOLO_MIRANDO_KEY] = True

        dialog = read_dialog_state(tool_context.state)
        update = args.to_update()

        if args.solo_mirando and update.is_empty():
            # Called only to flag that the user is "just looking", with no
            # new lead data -- valid, it shouldn't fall into EMPTY_UPDATE.
            snapshot = await lead_service.get_snapshot(UUID(tool_context.user_id), dialog.stage)
        else:
            try:
                snapshot = await lead_service.apply_update(
                    UUID(tool_context.user_id), update, dialog.stage
                )
            except DomainError as exc:
                return error(exc.code, exc.message, retryable=exc.retryable)
            tool_context.state[STAGE_KEY] = snapshot.stage.value

        return ok(
            {
                "lead": {
                    "nombre": snapshot.lead.nombre,
                    "canal_preferido": snapshot.lead.canal_preferido,
                    "uso_principal": snapshot.lead.uso_principal,
                    "tipo_vehiculo_interes": snapshot.lead.tipo_vehiculo_interes,
                    "motorizacion_interes": snapshot.lead.motorizacion_interes,
                    "nivel_interes": snapshot.lead.nivel_interes,
                    "consentimiento_contacto": snapshot.lead.consentimiento_contacto,
                },
                "etapa": snapshot.stage.value,
            }
        )

    return guardar_lead


def _first_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return f"{field}: {first['msg']}"
