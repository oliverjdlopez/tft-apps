"""Validated run definitions for the standalone composition benchmark."""

from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sweep(BaseModel):
    """Expand one algorithm or distance workload over a Cartesian parameter grid."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["adapter", "distance"] = "adapter"
    algorithm: str | None = None
    backends: list[Literal["cpu", "cuda"]] = Field(default_factory=lambda: ["cpu"])
    parameters: dict[str, list[Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_workload(self):
        """Reject empty axes and GPU labels on algorithms that still execute on CPU."""
        if not self.backends or len(set(self.backends)) != len(self.backends):
            raise ValueError("backends must be nonempty and unique")
        if any(not values for values in self.parameters.values()):
            raise ValueError("parameter axes must not be empty")
        if self.kind == "adapter" and (
            not self.algorithm
            or (
                "cuda" in self.backends
                and self.algorithm != "hdbscan"
            )
        ):
            raise ValueError(
                "CUDA adapter sweeps support only hdbscan"
            )
        if self.kind == "distance" and (self.algorithm or self.parameters):
            raise ValueError("distance sweeps use backends, not algorithm parameters")
        return self


class BenchmarkConfig(BaseModel):
    """Describe one reproducible sweep using a saved input or synthetic boards."""

    model_config = ConfigDict(extra="forbid")
    name: str = "Composition benchmark"
    sample_sizes: list[Annotated[int, Field(strict=True)]] = Field(
        default_factory=lambda: [100, 500, 1000, 2000]
    )
    seeds: list[Annotated[int, Field(strict=True)]] = Field(
        default_factory=lambda: [42]
    )
    repeats: int = Field(default=3, ge=1, le=20, strict=True)
    warmups: int = Field(default=1, ge=0, le=5, strict=True)
    input_path: str | None = None
    sweeps: list[Sweep] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_axes(self):
        """Keep samples bounded and reject ambiguous duplicated sweep dimensions."""
        for values, low, high in (
            (self.sample_sizes, 1, 2000),
            (self.seeds, 0, 2147483647),
        ):
            if not values or len(set(values)) != len(values):
                raise ValueError("sample_sizes and seeds must be nonempty and unique")
            if any(type(v) is not int or not low <= v <= high for v in values):
                raise ValueError(f"axis values must be integers in {low}..{high}")
        return self


class RunCase(BaseModel):
    """Freeze a validated workload, effective defaults, and sample selection."""

    case_id: str
    kind: Literal["adapter", "distance"]
    algorithm: str | None
    algorithm_version: str | None
    backend: Literal["cpu", "cuda"]
    sample_size: int
    seed: int
    parameters: dict[str, Any]
