"""Atomic persistent registry for Step 12 organization onboarding metadata.

The registry contains tenant IDs, membership metadata and onboarding state only.
It intentionally never stores database passwords, Supabase keys, Neo4j secrets,
or other connector credentials.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable

from .models import (
    OrganizationDataset,
    OrganizationRecord,
    OrganizationRegistryState,
    utc_now,
)


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_REGISTRY_FILE = PACKAGE_DIR / "workspace" / "organizations.json"
_TENANT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_tenant_id(value: str) -> str:
    tenant_id = str(value).strip()
    if not _TENANT_ID.fullmatch(tenant_id):
        raise ValueError(
            "tenant_id must start with a letter and contain only letters, digits, '.', '_' or '-' (3-64 chars)."
        )
    return tenant_id


def validate_safe_id(value: str, *, name: str = "id") -> str:
    text = str(value).strip()
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"{name} contains unsupported characters")
    return text


class OrganizationRegistry:
    def __init__(self, path: str | Path = DEFAULT_REGISTRY_FILE) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> OrganizationRegistryState:
        with self._lock:
            if not self.path.exists():
                return OrganizationRegistryState()
            payload = self.path.read_text(encoding="utf-8")
            if not payload.strip():
                return OrganizationRegistryState()
            return OrganizationRegistryState.model_validate_json(payload)

    def save(self, state: OrganizationRegistryState) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(state.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.path)

    def list(self) -> list[OrganizationRecord]:
        return sorted(self.load().organizations, key=lambda item: item.tenant_id)

    def get(self, tenant_id: str) -> OrganizationRecord:
        tenant = validate_tenant_id(tenant_id)
        for item in self.load().organizations:
            if item.tenant_id == tenant:
                return item
        raise KeyError(tenant)

    def exists(self, tenant_id: str) -> bool:
        try:
            self.get(tenant_id)
            return True
        except KeyError:
            return False

    def create(self, record: OrganizationRecord) -> OrganizationRecord:
        validate_tenant_id(record.tenant_id)
        with self._lock:
            state = self.load()
            if any(item.tenant_id == record.tenant_id for item in state.organizations):
                raise ValueError(f"Organization {record.tenant_id!r} already exists")
            state.organizations.append(record)
            self.save(state)
            return record

    def update(
        self,
        tenant_id: str,
        mutator: Callable[[OrganizationRecord], OrganizationRecord],
    ) -> OrganizationRecord:
        tenant = validate_tenant_id(tenant_id)
        with self._lock:
            state = self.load()
            for index, item in enumerate(state.organizations):
                if item.tenant_id != tenant:
                    continue
                updated = mutator(item.model_copy(deep=True))
                if updated.tenant_id != tenant:
                    raise ValueError("tenant_id cannot be changed after organization creation")
                updated.updated_at = utc_now()
                state.organizations[index] = updated
                self.save(state)
                return updated
            raise KeyError(tenant)

    def upsert_dataset(self, tenant_id: str, dataset: OrganizationDataset) -> OrganizationRecord:
        if dataset.tenant_id != tenant_id:
            raise ValueError("Dataset tenant_id does not match organization tenant_id")

        def mutate(org: OrganizationRecord) -> OrganizationRecord:
            for index, current in enumerate(org.datasets):
                if current.dataset_id == dataset.dataset_id:
                    org.datasets[index] = dataset
                    return org
            org.datasets.append(dataset)
            return org

        return self.update(tenant_id, mutate)

    def dataset(self, tenant_id: str, dataset_id: str) -> OrganizationDataset:
        validate_safe_id(dataset_id, name="dataset_id")
        org = self.get(tenant_id)
        for dataset in org.datasets:
            if dataset.dataset_id == dataset_id:
                return dataset
        raise KeyError(dataset_id)


DEFAULT_ORGANIZATION_REGISTRY = OrganizationRegistry()
