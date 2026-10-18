from enum import StrEnum


class Stage(StrEnum):
    NEW = "NEW"
    DISCOVERY = "DISCOVERY"
    CONCRETE_INTEREST = "CONCRETE_INTEREST"
    HANDOFF_PENDING = "HANDOFF_PENDING"
    HANDED_OFF = "HANDED_OFF"


class PreferredChannel(StrEnum):
    WHATSAPP = "WHATSAPP"
    CALL = "CALL"
    EMAIL = "EMAIL"
    CHAT = "CHAT"


class PrimaryUse(StrEnum):
    CITY = "CITY"
    WORK = "WORK"
    FAMILY = "FAMILY"
    TRAVEL = "TRAVEL"
    MIXED = "MIXED"


class VehicleType(StrEnum):
    SUV = "SUV"
    SEDAN = "SEDAN"
    HATCHBACK = "HATCHBACK"
    PICKUP = "PICKUP"
    VAN = "VAN"
    CROSSOVER = "CROSSOVER"
    OTHER = "OTHER"


class Powertrain(StrEnum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    HYBRID = "HYBRID"
    ELECTRIC = "ELECTRIC"
    LPG_CNG = "LPG_CNG"
    UNDEFINED = "UNDEFINED"


class InterestLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HandoffReason(StrEnum):
    TEST_DRIVE = "TEST_DRIVE"
    FORMAL_QUOTE = "FORMAL_QUOTE"
    IMMEDIATE_PURCHASE = "IMMEDIATE_PURCHASE"
    DISSATISFACTION = "DISSATISFACTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Urgency(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HandoffStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class KbCategory(StrEnum):
    BODY_TYPES = "BODY_TYPES"
    SEGMENTS = "SEGMENTS"
    POWERTRAIN = "POWERTRAIN"
    TRANSMISSION = "TRANSMISSION"
    FUEL_ECONOMY = "FUEL_ECONOMY"
    MAINTENANCE = "MAINTENANCE"
    SAFETY = "SAFETY"
    USAGE = "USAGE"
    GLOSSARY = "GLOSSARY"


class ToolStatus(StrEnum):
    OK = "ok"
    NO_RESULTS = "no_results"
    ERROR = "error"


class GuardrailLayer(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
