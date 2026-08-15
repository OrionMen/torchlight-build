"""Concrete structured sidecar parsers."""

from .equipment_parser import EQUIPMENT_DEFINITIONS, EquipmentDefinition, EquipmentParser
from .str_helmet import StrHelmetBaseAffixParser
from .legendary_equipment_parser import LegendaryDefinition, LegendaryEquipmentParser
from .vorax_equipment_parser import VoraxDefinition, VoraxEquipmentParser
from .memory_structured_parser import (
    HERO_MEMORY_SOURCE,
    MEMORY_REVIVAL_SOURCE,
    MEMORY_SOURCES,
    MemorySourceDefinition,
    MemoryStructuredParser,
)

__all__ = [
    "EQUIPMENT_DEFINITIONS",
    "EquipmentDefinition",
    "EquipmentParser",
    "StrHelmetBaseAffixParser",
    "LegendaryDefinition",
    "LegendaryEquipmentParser",
    "VoraxDefinition",
    "VoraxEquipmentParser",
    "HERO_MEMORY_SOURCE",
    "MEMORY_REVIVAL_SOURCE",
    "MEMORY_SOURCES",
    "MemorySourceDefinition",
    "MemoryStructuredParser",
]
