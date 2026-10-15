"""Validated resource metadata, structured records, and read provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResourceId = Annotated[str, Field(pattern=r'^(?:set[0-9]+(?:\.[0-9]+)?|(?:skill|playbook):[a-z0-9-]+)(?:/[a-z0-9-]+)*$')]


class ResourceMetadata(BaseModel):
    """Describe one resource without loading its content.

    Index children derive from parent IDs. Reference metadata remains separate
    from portable SKILL.md frontmatter. Views refer to structured record fields.
    """

    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)

    id: ResourceId
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=1024)]
    kind: Literal['index', 'reference', 'records', 'skill', 'skill-reference', 'playbook', 'playbook-reference']
    parent: ResourceId | None = None
    sets: tuple[Annotated[str, Field(pattern=r'^\d+(?:\.\d+)?$')], ...] = ()
    patches: tuple[str, ...] = ()
    requires: tuple[ResourceId, ...] = ()
    related: tuple[ResourceId, ...] = ()
    provenance: str = ''
    data_file: str | None = None
    views: tuple[Annotated[str, Field(pattern=r'^stage-(?:[1-9][0-9]*|all)$')], ...] = ()

    @model_validator(mode='after')
    def validate_storage(self) -> ResourceMetadata:
        """Reject inconsistent kind, scope, and backing-file metadata.

        Returns:
            Validated metadata safe for library construction.
        """
        if self.kind == 'records':
            if not self.data_file or Path(self.data_file).name != self.data_file or not self.data_file.endswith('.json'):
                raise ValueError('Records require a same-directory JSON data_file')
        elif self.data_file or self.views:
            raise ValueError('Only records may declare data_file or stage views')
        namespace = self.id.split(':', 1)[0]
        if namespace in {'skill', 'playbook'}:
            if self.kind not in {namespace, f'{namespace}-reference', 'index'}:
                raise ValueError(f'{namespace.title()} resources require a matching resource kind')
        elif self.kind in {'skill', 'skill-reference', 'playbook', 'playbook-reference'}:
            raise ValueError('Reference IDs cannot grant skill or playbook instructions')
        elif not self.sets or self.id.split('/')[0].removeprefix('set') not in self.sets:
            raise ValueError('Reference namespace must agree with explicit set scope')
        return self


class OfferWindow(BaseModel):
    """Retain an inclusive Wisp offer window as explicit stage/round endpoints."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    start: tuple[Annotated[int, Field(ge=1, le=20)], Annotated[int, Field(ge=1, le=20)]]
    end: tuple[Annotated[int, Field(ge=1, le=20)], Annotated[int, Field(ge=1, le=20)]]

    @model_validator(mode='after')
    def validate_order(self) -> OfferWindow:
        """Reject reversed windows instead of silently dropping eligibility.

        Returns:
            The ordered window.
        """
        if self.end < self.start:
            raise ValueError('Offer window end precedes start')
        return self


class WispRecord(BaseModel):
    """Preserve a complete variant claim with structured offer eligibility.

    Text retains exact source wording, including restrictions not yet normalized.
    Structured fields support stage views without reparsing that wording.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)
    id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    text: Annotated[str, Field(min_length=1)]
    offer_windows: tuple[OfferWindow, ...]
    all_stages: bool
    modes: tuple[str, ...]
    conditions: str | None
    augment_exclusions: str | None

    @model_validator(mode='after')
    def validate_eligibility(self) -> WispRecord:
        """Require either explicit windows or an explicit all-stage declaration.

        Returns:
            The complete variant record.
        """
        if self.all_stages == bool(self.offer_windows):
            raise ValueError('Declare windows or all_stages, exclusively')
        return self


class WispDocument(BaseModel):
    """Validate one authoritative Wisp category and its stable variant identities."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal[1]
    records: tuple[WispRecord, ...]

    @model_validator(mode='after')
    def validate_identities(self) -> WispDocument:
        """Reject duplicate IDs or names that would corrupt population counts.

        Returns:
            A losslessly addressable record population.
        """
        if not self.records:
            raise ValueError('Wisp collections cannot be empty')
        for values in ([record.id for record in self.records], [record.name for record in self.records]):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate Wisp record identity')
        return self


@dataclass(frozen=True)
class ResourceDescriptor:
    """Bind metadata to an approved source revision and optional derived view."""

    metadata: ResourceMetadata
    path: Path
    revision: tuple[int, int]
    data_path: Path | None = None
    data_revision: tuple[int, int] | None = None
    view: str | None = None


@dataclass(frozen=True)
class ResourceRead:
    """Record the exact resource revision actually returned during execution."""

    id: str
    path: str
    kind: str
    sha256: str
    content: str
    record_ids: tuple[str, ...] = ()


@dataclass
class ResourceLibrary:
    """Share a validated metadata snapshot and revision-specific lazy body cache."""

    entries: dict[str, ResourceDescriptor] = field(default_factory=dict)
    roots: tuple[str, ...] = ()
    body_cache: dict[str, ResourceRead] = field(default_factory=dict)
