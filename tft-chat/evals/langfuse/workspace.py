"""Public Langfuse APIs for portable workspace backups and native resources."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .utils import atomic_write, canonical_json


class Workspace:
    """Access the pinned platform without exporting authentication material."""

    def __init__(self, base_url: str, public_key: str, secret_key: str):
        """Create an authenticated transport for workspace maintenance."""
        self.http = httpx.Client(base_url=base_url, auth=(public_key, secret_key), timeout=30)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Call a public endpoint, keeping response bodies out of error logs."""
        response = self.http.request(method, '/api/public/' + path, **kwargs)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def list(self, path: str, *, cursor: bool = False, **params: Any) -> list[dict]:
        """Read every page using the endpoint's documented pagination contract."""
        rows = []
        query = {**params, 'limit': 100}
        if not cursor:
            query['page'] = 1
        seen = set()
        while True:
            response = self.request('GET', path, params=query)
            rows.extend(response['data'])
            meta = response.get('meta', {})
            if cursor:
                token = meta.get('nextCursor') or meta.get('cursor') or response.get('nextCursor')
                if not token:
                    break
                if token in seen:
                    raise ValueError('Platform returned a repeated pagination cursor')
                seen.add(token)
                query['cursor'] = token
            else:
                if query['page'] >= meta.get('totalPages', 1):
                    break
                query['page'] += 1
        return rows

    def export(self, destination: Path, *, native) -> dict:
        """Capture all dataset items, prompt versions, and historical run links.

        Args:
            destination: Private, immutable backup file written before migration.

        Returns:
            Complete exported definitions and existing experiment identities.
        """
        if destination.exists():
            raise FileExistsError('Workspace backup already exists; choose a new path')
        value = {'exported_at': datetime.now(timezone.utc).isoformat(), 'datasets': [],
                 'prompts': [], 'evaluators': [], 'rules': [], 'schema_version': 1}
        for dataset in self.list('v2/datasets'):
            name = quote(dataset['name'], safe='')
            details = self.request('GET', f'v2/datasets/{name}')
            details['items'] = native.items(dataset['id'])
            value['datasets'].append(details)
        for prompt in self.list('v2/prompts'):
            for version in prompt['versions']:
                value['prompts'].append(self.request('GET', 'v2/prompts/' + quote(prompt['name'], safe=''),
                                                     params={'version': version}))
        for evaluator in self.list('v2/evaluators', cursor=True):
            evaluator['versions'] = self.list(f"v2/evaluators/{evaluator['id']}/versions", cursor=True)
            value['evaluators'].append(evaluator)
        value['rules'] = self.list('v2/evaluation-rules', cursor=True)
        value['score_configs'] = self.list('score-configs')
        value['annotation_queues'] = self.list('annotation-queues')
        for queue in value['annotation_queues']:
            queue['items'] = self.list(f"annotation-queues/{queue['id']}/items")
        value['experiments'] = self.list('experiments', cursor=True, fromStartTime='1970-01-01T00:00:00Z')
        value['experiment_items'] = self.list('experiment-items', cursor=True,
            fromStartTime='1970-01-01T00:00:00Z', fields='core,dataset,io,metadata,itemMetadata,experimentMetadata,scores')
        value['scores'] = self.list('v3/scores', cursor=True, fields='details,subject,annotation')
        value['observations'] = self.list('v2/observations', cursor=True,
            fromStartTime='1970-01-01T00:00:00Z',
            fields='core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context')
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(destination, canonical_json(value))
        destination.chmod(0o600)
        return value

    def close(self) -> None:
        """Release the maintenance transport without affecting platform services."""
        self.http.close()
