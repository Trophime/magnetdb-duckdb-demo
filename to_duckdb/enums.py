"""
enums.py
========
Shared vocabulary for part/magnet types, mirroring the Django ORM's
``PartType``/``MagnetType`` enums. Kept dependency-free so any module
(crud, magnetdb, stress_map, checks, ...) can import it cheaply.
"""

import enum


class PartType(str, enum.Enum):
    SUPRA = "supra"
    HELIX = "helix"
    RING = "ring"
    SCREEN = "screen"
    LEAD = "lead"
    BITTER = "bitter"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]


class MagnetType(str, enum.Enum):
    INSERT = "insert"
    BITTERS = "bitters"
    SUPRAS = "supras"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]

    @property
    def supported_part_types(self) -> list[PartType]:
        if self == MagnetType.INSERT:
            return [PartType.HELIX, PartType.RING, PartType.SCREEN, PartType.LEAD]
        elif self == MagnetType.BITTERS:
            return [PartType.BITTER, PartType.SCREEN, PartType.LEAD]
        elif self == MagnetType.SUPRAS:
            return [PartType.SUPRA, PartType.SCREEN, PartType.LEAD]
        return []


# Part types that determine a magnet's assembly type (one and only one must
# be present among a magnet's parts — see crud.infer_magnet_type).
COIL_PART_TO_MAGNET_TYPE: dict[str, MagnetType] = {
    PartType.HELIX.value: MagnetType.INSERT,
    PartType.BITTER.value: MagnetType.BITTERS,
    PartType.SUPRA.value: MagnetType.SUPRAS,
}


class AssemblyStatus(str, enum.Enum):
    IN_STUDY = "in_study"
    IN_OPERATION = "in_operation"
    DISASSEMBLED = "disassembled"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]


class LifecycleStatus(str, enum.Enum):
    IN_OPERATION = "in_operation"
    IN_STOCK = "in_stock"
    IN_STUDY = "in_study"
    RETIRED = "retired"
    DEAD = "dead"

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]
