"""Outcome-free multiset features used by HDBSCAN discovery and matching."""

from collections import Counter
from .models import BoardObservation

FEATURE_REVISION = "structure.v1"


def structural_features(board: BoardObservation) -> dict[str, float]:
    """Encode roster multiplicity, holder investment, item instances, and trait states.

    Unit names remain canonical fact identities. Unknown traits have their own
    token; they are never treated as tier zero. Level and outcomes are excluded.
    """
    values = Counter()
    for u in board.units:
        values[f"unit:{u.unit.key}"] += 1.0
        match u.star_level: 
            case 1:
                pass # 1.0 is baseline
            case 2:
                values[f"star:{u.unit.key}:2"] += 0.2
            case 3:
                values[f"star:{u.unit.key}:3"] += 0.5
            case 4:
                values[f"star:{u.unit.key}:4"] += 1.0
            case _:
                values[f"star:{u.unit.key}:0"] += 0
        if u.items:
            match len(u.items):
                case 1:
                    values[f"holder:{u.unit.key}:1"] += 0.15
                case 2:
                    values[f"holder:{u.unit.key}:2"] += 0.7
                case 3:
                    values[f"holder:{u.unit.key}:3"] += 1.0
                case _:
                    values[f"holder:{u.unit.key}:0"] += 0
        
        for item in u.items:
            values[f"item:{u.unit.key}:{item.item.key}"] += 0.05 # Weigh specific items very lightly

    return dict(values)


