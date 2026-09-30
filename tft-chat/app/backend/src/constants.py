from enum import StrEnum



class ItemTypes(StrEnum):
    CRAFTABLE = "craftable"
    RADIANT = "radiant"
    ARTIFACT = "artifact"
    SUPPORT = "support"
    ANIMA = "anima"
    PSIONIC = "psionic"
    EMBLEM = "emblem"
    UNCRAFTABLE_EMBLEM = "uncraftable_emblem"
    FON = "fon" # Refers to any of the 3 fon-likes
    SPECIAL = "special" # Otherwise unclassifable items (e.g. crown of demacia)
    UNKNOWN = "unknown"

class TFTObjectTypes(StrEnum):
    UNIT = "unit"
    TRAIT = "trait"
    ITEM = "item"
    
    
