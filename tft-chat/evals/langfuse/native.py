"""Version-specific native adapter for operations without public equivalents."""
from __future__ import annotations

import json
from typing import Any
import httpx


class NativeWorkspace:
    """Authenticate the local project owner for dataset and webhook maintenance."""

    def __init__(self, base_url: str, email: str, password: str, project_id: str):
        """Establish a cookie session without exposing passwords to exports."""
        self.project_id = project_id
        self.http = httpx.Client(base_url=base_url, timeout=30, follow_redirects=True)
        csrf = self.http.get('/api/auth/csrf')
        csrf.raise_for_status()
        response = self.http.post('/api/auth/callback/credentials', data={
            'csrfToken': csrf.json()['csrfToken'], 'email': email, 'password': password,
            'callbackUrl': base_url, 'json': 'true'})
        response.raise_for_status()
        session = self.http.get('/api/auth/session')
        session.raise_for_status()
        if not session.json().get('user'):
            raise RuntimeError('Native workspace authentication failed')

    def call(self, operation: str, data: dict, *, read: bool = False) -> Any:
        """Call a verified pinned native operation with project ownership."""
        payload = {'json': {'projectId': self.project_id, **data}}
        if operation == 'itemsByDatasetId' and data.get('version'):
            payload['meta'] = {'values': {'version': ['Date']}}
        path = '/api/trpc/datasets.' + operation
        response = (self.http.get(path, params={'input': json.dumps(payload)}) if read
                    else self.http.post(path, json=payload))
        response.raise_for_status()
        value = response.json()
        if 'error' in value:
            raise ValueError(f'Native operation {operation} failed')
        return value['result']['data']['json']

    def items(self, dataset_id: str, *, version: str | None = None) -> list[dict]:
        """Read all current items, including archives omitted by the public v4 list."""
        rows = []
        page = 0
        while True:
            result = self.call('itemsByDatasetId', {'datasetId': dataset_id, 'page': page,
                                                   'limit': 100, 'filter': [], **({'version': version} if version else {})}, read=True)
            rows.extend(result['datasetItems'])
            if len(rows) >= result['totalDatasetItems']:
                return rows
            if not result['datasetItems']:
                raise ValueError('Native item pagination ended before its total count')
            page += 1

    def close(self) -> None:
        """Release the owner session after bounded maintenance operations."""
        self.http.close()
