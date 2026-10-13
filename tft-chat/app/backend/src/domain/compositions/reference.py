"""Reference-board classification and a minimal adapter contract fixture."""

from .models import BoardObservation, ReferenceParameters
from .models import FrozenModel, FitResult, Diagnostics
from .utils import family_from_boards, reference_assignment, model_distance_metric


class ReferenceAdapter:
    """Provide a one-reference fixture; not a production discovery algorithm."""

    algorithm_id = "reference_fixture"
    algorithm_version = "2"
    Parameters = ReferenceParameters

    def fit(self, boards, parameters, seed):
        """Freeze one reference for contract tests, handling empty input explicitly."""
        families = (family_from_boards("reference-1", boards),) if boards else ()
        model = FrozenModel(
            algorithm_id=self.algorithm_id,
            algorithm_version=self.algorithm_version,
            effective_parameters=parameters.model_dump(mode="json"),
            families=families,
            state={
                "references": [boards[0].model_dump(mode="json")] if boards else [],
                "seed": seed,
            },
        )
        return FitResult(
            model=model,
            discovery_assignments=self.classify(boards, model),
            diagnostics=Diagnostics(),
        )

    def classify(self, boards, model):
        """Reconstruct references exclusively from the serialized fixture model."""
        parameters = self.Parameters.model_validate(model.effective_parameters)
        refs = {
            f.family_id: tuple(
                BoardObservation.model_validate(b) for b in model.state["references"]
            )
            for f in model.families
        }
        return reference_assignments(
            boards,
            model.families,
            refs,
            parameters.rejection_distance,
            parameters.ambiguity_margin,
            metric=model_distance_metric(model),
        )


def reference_assignments(
    boards,
    families,
    references,
    rejection_distance,
    ambiguity_margin,
    *,
    accelerated=False,
    metric="euclidean",
):
    """Match frozen per-family reference boards with explicit rejection and ties.

    Args:
        boards: New outcome-free observations.
        families: Frozen definitions.
        references: Mapping from family id to nonempty reference board sequences.
        rejection_distance: Maximum accepted nearest-reference distance.
        ambiguity_margin: Minimum separation from the second viable family.
        accelerated: Use bounded CPU/CUDA matrix matching for supported adapters.
        metric: Euclidean for new models; weighted Jaccard for saved v1 models.
    """
    from .distance import board_distance
    from .acceleration import grouped_reference_distances

    retained = [f for f in families if references.get(f.family_id)]
    if accelerated:
        rows = grouped_reference_distances(
            boards, [references[f.family_id] for f in retained], metric=metric
        )
    else:
        rows = (
            [
                min(board_distance(board, ref, metric=metric) for ref in references[f.family_id])
                for f in retained
            ]
            for board in boards
        )
    return tuple(
        reference_assignment(
            board,
            sorted(
                (float(value), family.family_id) for value, family in zip(row, retained)
            ),
            rejection_distance,
            ambiguity_margin,
        )
        for board, row in zip(boards, rows)
    )
