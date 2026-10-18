"""rename_spanish_columns_to_english

Revision ID: 2592bdc6e309
Revises: aa3ad54be751
Create Date: 2026-09-27 17:46:55.136321

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2592bdc6e309"
down_revision: str | Sequence[str] | None = "aa3ad54be751"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# StrEnum *values* that changed as part of the rename (column renames alone
# don't touch existing rows -- without this, every pre-existing row keeps the
# old Spanish string, which is no longer a valid member of the new enum and
# breaks the moment the app tries to parse it, e.g. KbCategory("CARROCERIAS").
_PREFERRED_CHANNEL = {"LLAMADA": "CALL"}
_PRIMARY_USE = {
    "CIUDAD": "CITY",
    "TRABAJO": "WORK",
    "FAMILIA": "FAMILY",
    "VIAJES": "TRAVEL",
    "MIXTO": "MIXED",
}
_VEHICLE_TYPE = {"OTRO": "OTHER"}
_POWERTRAIN = {
    "GASOLINA": "GASOLINE",
    "HIBRIDO": "HYBRID",
    "ELECTRICO": "ELECTRIC",
    "GLP_GNV": "LPG_CNG",
    "NO_DEFINIDO": "UNDEFINED",
}
_INTEREST_LEVEL = {"BAJO": "LOW", "MEDIO": "MEDIUM", "ALTO": "HIGH"}
_HANDOFF_REASON = {
    "COTIZACION_FORMAL": "FORMAL_QUOTE",
    "COMPRA_INMEDIATA": "IMMEDIATE_PURCHASE",
    "DISCONFORMIDAD": "DISSATISFACTION",
    "FUERA_DE_ALCANCE": "OUT_OF_SCOPE",
}
_URGENCY = {"BAJA": "LOW", "MEDIA": "MEDIUM", "ALTA": "HIGH"}
_KB_CATEGORY = {
    "CARROCERIAS": "BODY_TYPES",
    "SEGMENTOS": "SEGMENTS",
    "MOTORIZACION": "POWERTRAIN",
    "TRANSMISION": "TRANSMISSION",
    "CONSUMO": "FUEL_ECONOMY",
    "MANTENIMIENTO": "MAINTENANCE",
    "SEGURIDAD": "SAFETY",
    "USO": "USAGE",
    "GLOSARIO": "GLOSSARY",
}


def _remap(table: str, column: str, mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(f"UPDATE {table} SET {column} = '{new}' WHERE {column} = '{old}'")


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("leads", "nombre", new_column_name="name")
    op.alter_column("leads", "telefono", new_column_name="phone")
    op.alter_column("leads", "canal_preferido", new_column_name="preferred_channel")
    op.alter_column("leads", "consentimiento_contacto", new_column_name="contact_consent")
    op.alter_column("leads", "uso_principal", new_column_name="primary_use")
    op.alter_column("leads", "tipo_vehiculo_interes", new_column_name="vehicle_type_interest")
    op.alter_column("leads", "motorizacion_interes", new_column_name="powertrain_interest")
    op.alter_column("leads", "nivel_interes", new_column_name="interest_level")

    op.alter_column("handoffs", "motivo", new_column_name="reason")
    op.alter_column("handoffs", "resumen_requerimiento", new_column_name="requirement_summary")
    op.alter_column("handoffs", "canal_preferido", new_column_name="preferred_channel")
    op.alter_column("handoffs", "urgencia", new_column_name="urgency")

    op.alter_column("kb_chunks", "categoria", new_column_name="category")
    op.drop_index(op.f("ix_kb_chunks_categoria"), table_name="kb_chunks")
    op.create_index(op.f("ix_kb_chunks_category"), "kb_chunks", ["category"], unique=False)

    _remap("leads", "preferred_channel", _PREFERRED_CHANNEL)
    _remap("leads", "primary_use", _PRIMARY_USE)
    _remap("leads", "vehicle_type_interest", _VEHICLE_TYPE)
    _remap("leads", "powertrain_interest", _POWERTRAIN)
    _remap("leads", "interest_level", _INTEREST_LEVEL)
    _remap("handoffs", "reason", _HANDOFF_REASON)
    _remap("handoffs", "preferred_channel", _PREFERRED_CHANNEL)
    _remap("handoffs", "urgency", _URGENCY)
    _remap("kb_chunks", "category", _KB_CATEGORY)


def downgrade() -> None:
    """Downgrade schema."""
    _remap("kb_chunks", "category", {v: k for k, v in _KB_CATEGORY.items()})
    _remap("handoffs", "urgency", {v: k for k, v in _URGENCY.items()})
    _remap("handoffs", "preferred_channel", {v: k for k, v in _PREFERRED_CHANNEL.items()})
    _remap("handoffs", "reason", {v: k for k, v in _HANDOFF_REASON.items()})
    _remap("leads", "interest_level", {v: k for k, v in _INTEREST_LEVEL.items()})
    _remap("leads", "powertrain_interest", {v: k for k, v in _POWERTRAIN.items()})
    _remap("leads", "vehicle_type_interest", {v: k for k, v in _VEHICLE_TYPE.items()})
    _remap("leads", "primary_use", {v: k for k, v in _PRIMARY_USE.items()})
    _remap("leads", "preferred_channel", {v: k for k, v in _PREFERRED_CHANNEL.items()})

    op.drop_index(op.f("ix_kb_chunks_category"), table_name="kb_chunks")
    op.alter_column("kb_chunks", "category", new_column_name="categoria")
    op.create_index(op.f("ix_kb_chunks_categoria"), "kb_chunks", ["categoria"], unique=False)

    op.alter_column("handoffs", "urgency", new_column_name="urgencia")
    op.alter_column("handoffs", "preferred_channel", new_column_name="canal_preferido")
    op.alter_column("handoffs", "requirement_summary", new_column_name="resumen_requerimiento")
    op.alter_column("handoffs", "reason", new_column_name="motivo")

    op.alter_column("leads", "interest_level", new_column_name="nivel_interes")
    op.alter_column("leads", "powertrain_interest", new_column_name="motorizacion_interes")
    op.alter_column("leads", "vehicle_type_interest", new_column_name="tipo_vehiculo_interes")
    op.alter_column("leads", "primary_use", new_column_name="uso_principal")
    op.alter_column("leads", "contact_consent", new_column_name="consentimiento_contacto")
    op.alter_column("leads", "preferred_channel", new_column_name="canal_preferido")
    op.alter_column("leads", "phone", new_column_name="telefono")
    op.alter_column("leads", "name", new_column_name="nombre")
