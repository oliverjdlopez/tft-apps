"""Test hierarchical discovery, lazy reads, strict schemas, and source preservation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from domain.resources.catalogue import read_resource_content, resource_entries
from domain.resources.library import build_library, get_library, read_content, validate_library
from domain.resources.models import ResourceMetadata, WispDocument
from domain.runtime.models import PreparedResources, ResourceAccess


def document(root: Path, name: str, metadata: dict, body: str = 'COMPLETE BODY') -> Path:
    """Write an authored resource without deriving identity from its filename."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\n' + yaml.safe_dump(metadata, sort_keys=False) + '---\n' + body)
    return path


def metadata(resource_id: str, kind: str = 'index', parent: str | None = None, **extra) -> dict:
    """Create explicit set-scoped metadata for isolated fixture resources."""
    return dict(id=resource_id, title=resource_id, description='Discovery description',
                kind=kind, parent=parent, sets=['18'], **extra)


@pytest.fixture
def roots(tmp_path):
    """Create a hierarchy with source facts and skill-only supporting instructions."""
    references, skills = tmp_path / 'references', tmp_path / 'skills'
    references.mkdir()
    skills.mkdir()
    document(references, 'index.md', metadata('set18'))
    document(references, 'topic/index.md', metadata('set18/units', parent='set18'))
    document(references, 'topic/facts.md', metadata('set18/units/roster', 'reference', 'set18/units'),
             '# Full roster\nFirst fact\nLast fact\n')
    package = skills / 'workflow'
    package.mkdir()
    (package / 'SKILL.md').write_text('---\nname: workflow\ndescription: A workflow\n---\nFULL WORKFLOW')
    document(package, 'references/example.md', dict(id='skill:workflow/example', title='Example',
             description='Supporting example', kind='skill-reference', parent='skill:workflow'), 'PRIVATE EXAMPLE')
    return references, skills, tmp_path / 'playbooks'


def prepared(library, *, skills=(), references=True):
    """Bind two distinct assistant permissions to the same validated library."""
    return PreparedResources(library=library, set_number=18, access={
        'reader': ResourceAccess(references=references, skills=skills),
        'denied': ResourceAccess(),
    })


def test_discovery_is_header_only_and_content_is_cached(roots, monkeypatch):
    """Building and rendering directories never load any body or backing JSON."""
    original = Path.read_bytes
    reads = []

    def counted(path):
        """Track actual complete body reads at the filesystem boundary."""
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', counted)
    library = build_library(*roots)
    resources = prepared(library)
    assert not reads and not library.body_cache
    assert [entry['id'] for entry in resource_entries(resources, 'reader')] == ['set18']
    index = read_resource_content(resources, 'reader', 'set18')
    assert [child['id'] for child in index['children']] == ['set18/units']
    assert len(reads) == 1
    assert 'Last fact' not in index['content']
    facts = read_resource_content(resources, 'reader', 'set18/units/roster')
    assert 'First fact' in facts['content'] and 'Last fact' in facts['content']
    read_resource_content(resources, 'reader', 'set18/units/roster')
    assert len(reads) == 2 and len(resources.reads) == 2


def test_metadata_and_body_cache_invalidate_without_mutating_old_runs(roots):
    """Prepared revisions fail closed before first read if authoring changes them."""
    first = get_library(*roots)
    assert get_library(*roots) is first
    target = roots[0] / 'topic/facts.md'
    target.write_text(target.read_text().replace('First fact', 'Changed fact'))
    second = get_library(*roots)
    assert second is not first
    with pytest.raises(ValueError, match='changed after preparation'):
        read_content(first, 'set18/units/roster')
    assert 'Changed fact' in read_content(second, 'set18/units/roster').content
    target.write_text(target.read_text().replace('Changed fact', 'Another revision'))
    assert 'Changed fact' in read_content(second, 'set18/units/roster').content


def test_resource_ids_survive_file_moves(roots):
    """Moving approved storage changes provenance without breaking identity."""
    before = build_library(*roots)
    source = roots[0] / 'topic/facts.md'
    source.rename(roots[0] / 'different-file.md')
    after = build_library(*roots)
    assert set(before.entries) == set(after.entries)
    assert read_content(after, 'set18/units/roster').content.endswith('Last fact\n')


def test_child_reads_inherit_permissions_even_when_ids_are_known(roots):
    """An index link or guessed ID never grants reference or skill access."""
    resources = prepared(build_library(*roots), skills=('workflow',))
    assert read_resource_content(resources, 'reader', 'skill:workflow')['children'][0]['id'] == 'skill:workflow/example'
    assert read_resource_content(resources, 'reader', 'skill:workflow/example')['content'] == 'PRIVATE EXAMPLE'
    for resource_id in ('set18', 'set18/units/roster', 'skill:workflow', 'skill:workflow/example'):
        assert not read_resource_content(resources, 'denied', resource_id)['found']
    assert resource_entries(resources, 'denied', 'skill:workflow') == []
    resources.set_number = 17
    assert not read_resource_content(resources, 'reader', 'set18/units/roster')['found']
    assert read_resource_content(resources, 'reader', 'skill:workflow/example')['found']


@pytest.mark.parametrize('mutation, message', [
    ({'parent': 'set18/missing'}, 'Broken resource link'),
    ({'requires': ['set18/missing']}, 'Broken resource link'),
    ({'id': 'set18'}, 'Duplicate resource ID'),
    ({'sets': ['17']}, 'set scope'),
    ({'description': ''}, 'description'),
    ({'extra_field': 'unexpected'}, 'extra_field'),
])
def test_invalid_graphs_and_metadata_are_rejected(roots, mutation, message):
    """Invalid resources cannot silently disappear from model discovery."""
    fields = metadata('set18/units/roster', 'reference', 'set18/units')
    fields.update(mutation)
    document(roots[0], 'topic/facts.md', fields)
    with pytest.raises(ValueError, match=message):
        build_library(*roots)


def test_duplicate_yaml_keys_and_symlink_sources_are_rejected(roots, tmp_path):
    """Ambiguous metadata and filesystem escapes fail before any read capability."""
    target = roots[0] / 'topic/facts.md'
    original = target.read_text()
    target.write_text(original.replace('id: set18/units/roster', 'id: set18/units/roster\nid: set18/units/other'))
    with pytest.raises(ValueError, match='Duplicate metadata key'):
        build_library(*roots)
    target.unlink()
    outside = tmp_path / 'outside.md'
    outside.write_text(original)
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='escapes approved roots'):
        build_library(*roots)


def test_record_views_cover_overlaps_all_stage_variants_and_full_populations():
    """Every source variant survives migration and structured stage intersections."""
    library = validate_library()
    records = [entry for entry in library.entries.values()
               if entry.metadata.kind == 'records' and entry.view is None]
    assert len(records) == 7
    assert sum(len(json.loads(entry.data_path.read_text())['records']) for entry in records) == 365
    for descriptor in records:
        document = WispDocument.model_validate_json(descriptor.data_path.read_bytes())
        full = read_content(library, descriptor.metadata.id)
        assert len(full.record_ids) == len(document.records)
        reconstructed = set()
        for view in descriptor.metadata.views:
            result = read_content(library, f'{descriptor.metadata.id}/{view}')
            reconstructed.update(result.record_ids)
            stage = view.removeprefix('stage-')
            expected = {record.id for record in document.records if (
                record.all_stages if stage == 'all' else any(
                    window.start[0] <= int(stage) <= window.end[0] for window in record.offer_windows))}
            assert set(result.record_ids) == expected
            for record in document.records:
                if record.id in expected:
                    assert record.text in result.content
        assert reconstructed == set(full.record_ids)
    all_stage = read_content(library, 'set18/wisps/offers-goldxp/stage-all')
    assert 'Truce (prismatic)' in all_stage.content


def test_record_validation_rejects_unknown_windows_and_false_views(roots):
    """Typed data rejects ambiguous eligibility instead of regex fallback."""
    record = {'id': 'variant', 'name': 'Variant', 'text': 'Complete original wording',
              'offer_windows': [{'start': [4, 7], 'end': [3, 1]}], 'all_stages': False,
              'modes': ['Standard'], 'conditions': None, 'augment_exclusions': None}
    with pytest.raises(ValueError, match='precedes'):
        WispDocument.model_validate({'schema_version': 1, 'records': [record]})
    record['offer_windows'] = [{'start': [3, 5], 'end': [4, 1]}]
    fields = metadata('set18/units/offers', 'records', 'set18/units', data_file='offers.json', views=['stage-2'])
    document(roots[0], 'topic/offers.md', fields)
    (roots[0] / 'topic/offers.json').write_text(json.dumps({'schema_version': 1, 'records': [record]}))
    with pytest.raises(ValueError, match='views disagree'):
        validate_library(*roots)


def test_record_backing_files_cannot_be_orphaned(roots):
    """Only explicitly declared typed records may remain in reference storage."""
    (roots[0] / 'unowned.json').write_text('{}')
    with pytest.raises(ValueError, match='exactly one declared record owner'):
        build_library(*roots)


def test_required_dependencies_cannot_cycle(roots):
    """Required reads must terminate even when related-resource links are mutual."""
    document(roots[0], 'topic/facts.md', metadata('set18/units/roster', 'reference', 'set18/units',
                                               requires=['set18/units/other']))
    document(roots[0], 'topic/other.md', metadata('set18/units/other', 'reference', 'set18/units',
                                               requires=['set18/units/roster']))
    with pytest.raises(ValueError, match='Cyclic required'):
        build_library(*roots)


def test_stage_reads_link_rules_and_unrestricted_variants():
    """Stage discovery supplies all dependencies needed to interpret its population."""
    resources = prepared(build_library())
    result = read_resource_content(resources, 'reader', 'set18/wisps/offers-goldxp/stage-2')
    assert result['found'] and result['record_ids']
    assert result['requires'] == ('set18/wisps/rules', 'set18/wisps/offers-goldxp/stage-all')
    full = read_resource_content(resources, 'reader', 'set18/wisps/offers-goldxp')
    assert full['sha256'] == result['sha256'] and full['content'] != result['content']


def test_authoritative_collections_cannot_reuse_variant_identities(roots):
    """Two independently authored populations must not hide duplicate variants."""
    record = {'id': 'same-variant', 'name': 'Same variant', 'text': 'Original full wording',
              'offer_windows': [], 'all_stages': True, 'modes': [],
              'conditions': None, 'augment_exclusions': None}
    for name in ('first', 'second'):
        document(roots[0], f'topic/{name}.md', metadata(f'set18/units/{name}', 'records',
                 'set18/units', data_file=f'{name}.json', views=['stage-all']))
        (roots[0] / f'topic/{name}.json').write_text(json.dumps({'schema_version': 1, 'records': [record]}))
    with pytest.raises(ValueError, match='multiple authoritative owners'):
        validate_library(*roots)


@pytest.fixture
def playbook_roots(roots):
    """Add a specific guide whose name deliberately matches an existing skill."""
    package = roots[2] / 'workflow'
    document(package, 'PLAYBOOK.md', {'name': 'workflow', 'description': 'Specific task guide'},
             'FULL SPECIFIC GUIDE')
    document(package, 'references/example.md', dict(id='playbook:workflow/example', title='Example',
             description='Guide example', kind='playbook-reference', parent='playbook:workflow'), 'GUIDE EXAMPLE')
    return roots


def test_playbooks_have_independent_discovery_reads_and_child_permissions(playbook_roots):
    """Identically named skills and guides never grant access to each other."""
    library = build_library(*playbook_roots)
    resources = PreparedResources(library=library, set_number=18, access={
        'guide': ResourceAccess(playbooks=('workflow',)),
        'general': ResourceAccess(skills=('workflow',)),
    })
    assert [entry['id'] for entry in resource_entries(resources, 'guide')] == ['playbook:workflow']
    assert not library.body_cache
    guide = read_resource_content(resources, 'guide', 'playbook:workflow')
    assert guide['content'] == 'FULL SPECIFIC GUIDE' and guide['kind'] == 'playbook'
    assert guide['children'][0]['id'] == 'playbook:workflow/example'
    assert read_resource_content(resources, 'guide', 'playbook:workflow/example')['content'] == 'GUIDE EXAMPLE'
    assert not read_resource_content(resources, 'guide', 'skill:workflow')['found']
    assert read_resource_content(resources, 'general', 'skill:workflow')['found']
    assert not read_resource_content(resources, 'general', 'playbook:workflow/example')['found']


def test_playbook_changes_invalidate_metadata_and_retain_cached_reads(playbook_roots):
    """Guide edits refresh discovery while completed reads retain their revision."""
    first = get_library(*playbook_roots)
    original = read_content(first, 'playbook:workflow')
    path = playbook_roots[2] / 'workflow/PLAYBOOK.md'
    path.write_text(path.read_text().replace('FULL SPECIFIC GUIDE', 'REVISED SPECIFIC GUIDE'))
    second = get_library(*playbook_roots)
    assert second is not first
    assert read_content(first, 'playbook:workflow') == original
    assert read_content(second, 'playbook:workflow').content == 'REVISED SPECIFIC GUIDE'


@pytest.mark.parametrize('mutation, message', [
    ({'name': 'different'}, 'must match'),
    ({'name': '../escape'}, 'Invalid playbook name'),
    ({'description': ''}, 'description'),
    ({'keywords': ['custom']}, 'Unsupported playbook protocol'),
])
def test_playbook_entrypoint_validation(playbook_roots, mutation, message):
    """Specific guides enforce the same strict package metadata as skills."""
    fields = {'name': 'workflow', 'description': 'A guide'}
    fields.update(mutation)
    document(playbook_roots[2] / 'workflow', 'PLAYBOOK.md', fields)
    with pytest.raises(ValueError, match=message):
        build_library(*playbook_roots)


@pytest.mark.parametrize('kind', ['skill-reference', 'reference'])
def test_playbook_namespace_cannot_claim_other_resource_kinds(kind):
    """Guide IDs cannot masquerade as general guidance or factual material."""
    with pytest.raises(ValueError, match='matching resource kind'):
        ResourceMetadata(id='playbook:workflow/example', title='Example', description='Example', kind=kind)


def test_playbook_storage_and_parent_boundaries(playbook_roots):
    """Supporting guides cannot cross package ownership or storage namespaces."""
    package = playbook_roots[2] / 'workflow'
    fields = dict(id='playbook:workflow/example', title='Example', description='Example',
                  kind='playbook-reference', parent='skill:workflow')
    document(package, 'references/example.md', fields)
    with pytest.raises(ValueError, match='inherit its package'):
        build_library(*playbook_roots)
    fields.update(id='skill:workflow/other', parent='skill:workflow', kind='skill-reference')
    document(package, 'references/example.md', fields)
    with pytest.raises(ValueError, match='namespace does not match'):
        build_library(*playbook_roots)
