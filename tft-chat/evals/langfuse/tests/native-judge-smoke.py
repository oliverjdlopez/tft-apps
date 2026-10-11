"""Run all native judge profiles against the mock endpoint in isolated CI only."""
from __future__ import annotations

from functools import partial
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from langfuse import Langfuse

from evals.langfuse.grading import freeze_grading, reconcile_report
from evals.langfuse.utils import configured_workspace, load_grading_registry, atomic_write, canonical_json


def output_task(*, item, client, profile, failing, **kwargs):
    """Publish representative synthetic output; the native worker performs grading."""
    client.update_current_span(metadata={'quality_profile': profile, 'execution': 'live',
        'execution_success': 'true', 'execution_evidence': {'source': 'mock scheduling acceptance'}})
    return 'TEST_FAILURE: contradicted requirements' if failing else 'Requirements satisfied.'


def main():
    """Verify scheduling, explanations, and final gates without paid model calls."""
    if os.environ.get('LANGFUSE_TEST_DEPLOYMENT') != '1':
        raise RuntimeError('Native mock scheduling tests require an isolated test deployment')
    workspace = configured_workspace()
    connections = workspace.list('llm-connections')
    if not any('mock-model:8000' in (connection.get('baseURL') or '') for connection in connections):
        raise RuntimeError('Refusing native mock tests without a verified local mock connection')
    registry = load_grading_registry()
    grading = freeze_grading(workspace, registry)
    from dotenv import dotenv_values
    local = dotenv_values(Path(__file__).parents[1] / '.env')
    client = Langfuse(base_url=os.environ.get('LANGFUSE_BASE_URL', 'http://localhost:15510'),
                     public_key=os.environ.get('LANGFUSE_PUBLIC_KEY') or local['LANGFUSE_PUBLIC_KEY'],
                     secret_key=os.environ.get('LANGFUSE_SECRET_KEY') or local['LANGFUSE_SECRET_KEY'])
    dataset = client.get_dataset('end-to-end')
    started = datetime.now(timezone.utc)
    report = {'group_id': 'mock-native-' + started.isoformat(), 'started_at': started.isoformat(),
              'grading_deadline': time.time() + 600, 'experiments': []}
    try:
        for profile in grading['evaluators']:
            for failing in (False, True):
                name = f'mock calibration {profile} {failing} {started.isoformat()}'
                result = client.run_experiment(name=name, run_name=name, data=[dataset.items[0]],
                    task=partial(output_task, client=client, profile=profile, failing=failing))
                row = result.item_results[0]
                report['experiments'].append({'dataset_run_id': result.dataset_run_id, 'expected_pass': not failing,
                    'items': [{'remote_id': row.item.id, 'trace_id': row.trace_id, 'execution_success': True,
                               'contract_pass': True, 'quality_profile': profile, 'quality_threshold': .8}]})
        client.flush()
        while True:
            report = reconcile_report(workspace, report, grading)
            if report['state'] != 'awaiting_scores':
                break
            time.sleep(2)
        for experiment in report['experiments']:
            assert experiment['passed'] == experiment['expected_pass'], experiment
            assert experiment['items'][0].get('quality_score'), experiment
        atomic_write(Path('/tmp/chattft-native-judge-report.json'), canonical_json(report))
        print('All five native profiles scheduled, explained, and gated successful/failing mock outputs.')
    finally:
        client.shutdown()
        workspace.close()


if __name__ == '__main__':
    main()
