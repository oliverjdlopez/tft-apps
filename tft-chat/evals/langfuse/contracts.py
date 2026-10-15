"""Natural dataset contracts and lossless conversion of historical definitions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import validate
from domain.assistants.constants import AssistantName

from .utils import check_assertion, legacy_execution_item

# Retired transcript names remain literal archive identities for lossless
# historical conversion; they are no longer registered AssistantName members.
DATASET_NAMES = {
    AssistantName.CHAT: 'end-to-end',
    'context_response_smoke': 'context-response',
    'chat_intake': 'chattft/intake/unscored-prompts',
    AssistantName.DATA_ANALYST: 'data-analysis',
    'clean_transcript': 'chattft/transcripts/cleanup',
    'compact_transcript': 'chattft/transcripts/compaction',
    AssistantName.DUMMY_ASSISTANT: 'internal/fixtures/deterministic-trace',
    'analyze_transcript': 'archive/analyze-transcript',
}
ACTIVE_WORKFLOW_SUITES = frozenset({AssistantName.CHAT, AssistantName.DATA_ANALYST, 'context_response_smoke'})

QUALITY_PROFILES = {
    'chat_product_quality': 'answer_quality', 'expert_not_coach': 'answer_quality',
    'deep_analysis_quality': 'answer_quality', 'unit_ranking_quality': 'answer_quality',
    'item_family_quality': 'answer_quality', 'artifact_ranking_quality': 'answer_quality',
    'emblem_ranking_quality': 'answer_quality', 'trait_unit_quality': 'answer_quality',
    'cohort_delta_quality': 'answer_quality', 'multi_part_analysis_quality': 'answer_quality',
    'player_review_quality': 'scope_honesty', 'scope_honesty_quality': 'scope_honesty',
    'rolldown_answer_quality': 'rolldown_quality',
    'terminology_preservation': 'terminology_preservation', 'signal_retention': 'signal_retention',
}
PROFILE_DEFAULTS = {AssistantName.CHAT: 'answer_quality', AssistantName.DATA_ANALYST: 'answer_quality',
                    'clean_transcript': 'terminology_preservation',
                    'compact_transcript': 'signal_retention'}


def dataset_schemas(suite: dict, *, version: int = 2) -> dict:
    """Return native application-input and desired-output validation schemas."""
    if suite.get('assistant', suite['name']) in {AssistantName.CHAT, AssistantName.DATA_ANALYST}:
        fields = {'messages': {'type': 'array', 'minItems': 1, 'items': {
            'type': 'object', 'properties': {'role': {'enum': ['user', 'assistant']},
                                           'content': {'type': 'string'}},
            'required': ['role', 'content'], 'additionalProperties': False}}}
    else:
        fields = {'text': {'type': 'string'}}
    input_schema = {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
    if suite.get('scoring') == 'none':
        expected_schema = None
    else:
        expected_schema = {'oneOf': [{'type': 'string'}, {'type': 'object', 'properties': {
            'requirements': {'type': 'array', 'items': {'type': 'string'}},
            'reference': {'type': 'string'}}, 'additionalProperties': False}]}
    if version >= 3:
        input_schema = {'type': 'string'}
        # Langfuse treats omitted expected output as undefined, not JSON null.
        # Mixed chat datasets validate scored references in the runner instead.
        if suite.get('assistant', suite['name']) == AssistantName.CHAT:
            expected_schema = None
    return {'input': input_schema, 'expected_output': expected_schema}


def migrate_item(suite: dict, item: dict) -> tuple[dict, list[dict]]:
    """Convert one case without losing authored expectations or original definitions.

    Args:
        suite: Stable CLI identity and execution family.
        item: Complete source item, including optional hosted linkage.

    Returns:
        Converted item and one audit entry for each original assertion.
    """
    result = deepcopy(item)
    if not isinstance(item['input'], dict) or 'input' not in item['input']:
        return result, []
    metadata = result.setdefault('metadata', {})
    metadata['contract_version'] = 2
    metadata['legacy_definition'] = deepcopy(item)
    original = item['input']
    result['input'] = ({'messages': [{'role': 'user', 'content': original['input']}]}
                       if suite.get('assistant', suite['name']) in {AssistantName.CHAT, AssistantName.DATA_ANALYST}
                       else {'text': original['input']})
    if original.get('fixture'):
        metadata['fixture'] = deepcopy(original['fixture'])
    result['expected_output'] = {'requirements': []}
    metadata['deterministic_checks'] = []
    manifest = []
    profiles = set()
    for assertion in item['expected_output']['assertions']:
        entry = {'case_id': item['id'], 'assertion': deepcopy(assertion)}
        if assertion['kind'] == 'rubric':
            profile = QUALITY_PROFILES.get(assertion['name'], PROFILE_DEFAULTS.get(suite['name']))
            if profile is None:
                raise ValueError(f"No quality profile for {item['id']}/{assertion['name']}")
            profiles.add(profile)
            result['expected_output']['requirements'].append(assertion['rubric'])
            entry.update(destination='expected_output.requirements', evaluator=profile,
                         requirement_index=len(result['expected_output']['requirements']) - 1)
        else:
            metadata['deterministic_checks'].append(deepcopy(assertion))
            entry.update(destination='metadata.deterministic_checks', check=assertion['name'])
        manifest.append(entry)
    if len(profiles) > 1:
        raise ValueError('Mixed quality profiles require explicit migration review')
    if profiles or suite['name'] in PROFILE_DEFAULTS:
        metadata['quality_profile'] = next(iter(profiles), PROFILE_DEFAULTS.get(suite['name']))
        # Keep every authored threshold; consolidation never relaxes a gate.
        thresholds = [a.get('threshold', .8) for a in item['expected_output']['assertions'] if a['kind'] == 'rubric']
        metadata['quality_threshold'] = max(thresholds, default=.8)
    result.setdefault('status', 'ACTIVE')
    return result, manifest


def migrate_bundle(bundle: dict) -> dict:
    """Create a new snapshot definition while leaving old content immutable."""
    if bundle.get('schema_version') in {2, 3}:
        return deepcopy(bundle)
    result = deepcopy(bundle)
    result.update(schema_version=2, schemas=dataset_schemas(bundle['suite']), assertion_manifest=[])
    result['dataset_name'] = DATASET_NAMES[bundle['suite']['name']]
    result['items'] = []
    for item in bundle['items']:
        converted, manifest = migrate_item(bundle['suite'], item)
        result['items'].append(converted)
        result['assertion_manifest'].extend(manifest)
    result['acceptance'] = {'execution_success': True, 'all_required_checks': True,
                            'quality_threshold': .8, 'grading_deadline_seconds': 600,
                            'evaluator_drift_passes': False}
    result['historical_comparability'] = 'Rubric consolidation does not preserve numerical equivalence.'
    return result


def validate_natural_item(suite: dict, item: dict, *, version: int = 2) -> None:
    """Validate UI-authored cases without demanding internal assertion scaffolding."""
    schemas = dataset_schemas(suite, version=version)
    validate(item['input'], schemas['input'])
    metadata = item.get('metadata', {})
    if suite.get('scoring') == 'none' or (version >= 3 and metadata.get('scoring') == 'none'):
        if item.get('expected_output') is not None:
            raise ValueError('Unscored cases must omit expected output')
        forbidden = {'deterministic_checks', 'quality_profile', 'quality_threshold'} & set(metadata)
        if forbidden:
            raise ValueError(f"Unscored cases cannot configure grading metadata: {sorted(forbidden)}")
        return
    if item.get('expected_output') is None and not reference_is_optional(suite, item, version=version):
        raise ValueError('Scored cases require expected output')
    if item.get('expected_output') is not None:
        expected_schema = schemas['expected_output'] or dataset_schemas(suite)['expected_output']
        validate(item['expected_output'], expected_schema)
    checks = metadata.get('deterministic_checks', [])
    names = set()
    for check in checks:
        check_assertion(check)
        if check['kind'] == 'rubric' or check['name'] in names:
            raise ValueError('Deterministic checks must be unique and cannot contain Python rubrics')
        names.add(check['name'])
    profile = metadata.get('quality_profile', PROFILE_DEFAULTS.get(suite['name']))
    if suite['name'] in PROFILE_DEFAULTS and profile is None:
        raise ValueError('Assistant cases require a native quality profile')
    if profile is not None and profile not in set(QUALITY_PROFILES.values()):
        raise ValueError('Unknown native quality profile')
    threshold = metadata.get('quality_threshold', .8)
    if type(threshold) not in {float, int} or not 0 <= threshold <= 1:
        raise ValueError('Quality threshold must be between zero and one')


def reference_is_optional(suite: dict, item: dict, *, version: int) -> bool:
    """Accept a missing hosted reference during dataset freeze for check-only cases.

    Langfuse stores an empty expected-output string as null. The context and
    response smoke cases intentionally have no reference text or native judge,
    so their authored trace checks remain the scoring contract.
    """
    metadata = item.get('metadata', {})
    checks = metadata.get('deterministic_checks') if isinstance(metadata, dict) else None
    return (version >= 3 and suite['name'] not in PROFILE_DEFAULTS
            and isinstance(metadata, dict)
            and isinstance(checks, list) and bool(checks)
            and metadata.get('quality_profile') is None)
