"""Minimal working adapter fixture used to freeze the extension contract."""

from .models import BoardObservation, ReferenceParameters
from .models import FrozenModel, FitResult, Diagnostics
from .utils import family_from_boards, reference_assignments, model_distance_metric


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
