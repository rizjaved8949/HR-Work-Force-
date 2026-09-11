from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterator

import pandas as pd


DEFAULT_SOURCE_MAP_FILE = "HR_Decision_Data_Source_Map.csv"

# These are the tables used by the existing deterministic successor pipeline.
# In Supabase mode they are materialized to a temporary directory so the same
# successor scoring/ranking code can be reused without changing its logic.
SUCCESSOR_DATASET_KEYS = (
    "employee_profile",
    "employee_experience",
    "employee_performance",
    "employee_attendance",
    "employee_skills",
    "position_master",
    "position_requirements",
    "position_skill_requirements",
    "skill_catalog",
)


class DecisionCaseDataRepository:
    """Read-only HR data access for the Decision Trigger Engine.

    The trigger engine calls only ``read(key)`` and therefore does not care
    whether the underlying HR data is CSV today or Supabase later.

    Current mode (default):
        DECISION_CASE_DATA_SOURCE=csv

    Future mode:
        DECISION_CASE_DATA_SOURCE=supabase

    Dataset-to-file/table names live in ``HR_Decision_Data_Source_Map.csv`` so
    a future Supabase migration does not require changing trigger-rule code.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        source: str | None = None,
        client_factory: Callable[[], Any] | None = None,
        source_map_file: str | Path | None = None,
        page_size: int = 1000,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.source = (source or os.getenv("DECISION_CASE_DATA_SOURCE", "csv")).strip().lower()
        self.client_factory = client_factory
        self.page_size = max(100, int(page_size))

        if self.source not in {"csv", "supabase"}:
            raise ValueError(
                "DECISION_CASE_DATA_SOURCE must be either 'csv' or 'supabase'."
            )

        map_path = Path(
            source_map_file
            or os.getenv("DECISION_CASE_SOURCE_MAP", DEFAULT_SOURCE_MAP_FILE)
        )
        if not map_path.is_absolute():
            map_path = self.data_dir / map_path
        self.source_map_path = map_path

        if not self.source_map_path.is_file():
            raise FileNotFoundError(
                f"Decision Trigger data-source map was not found: {self.source_map_path}"
            )

        self._mapping = self._load_mapping(self.source_map_path)

        if self.source == "csv":
            if not self.data_dir.is_dir():
                raise FileNotFoundError(
                    f"Decision-case CSV data folder was not found: {self.data_dir}"
                )
            self._validate_csv_files()
        elif self.client_factory is None:
            raise RuntimeError(
                "Supabase source mode requires a Supabase client factory."
            )

    @staticmethod
    def _load_mapping(path: Path) -> dict[str, dict[str, str]]:
        frame = pd.read_csv(path).fillna("")
        required = {"Dataset_Key", "CSV_File", "Supabase_Table"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                "Decision Trigger data-source map is missing columns: "
                + ", ".join(sorted(missing))
            )

        mapping: dict[str, dict[str, str]] = {}
        for row in frame.to_dict("records"):
            key = str(row["Dataset_Key"]).strip()
            if not key:
                continue
            mapping[key] = {
                "csv_file": str(row["CSV_File"]).strip(),
                "supabase_table": str(row["Supabase_Table"]).strip(),
            }
        return mapping

    def _validate_csv_files(self) -> None:
        missing: list[str] = []
        for key, item in self._mapping.items():
            # Runtime/output/config-only datasets do not have to be present as
            # source HR data. They are created/handled by their own components.
            if key.startswith("decision_"):
                continue
            csv_file = item.get("csv_file", "")
            if csv_file and not (self.data_dir / csv_file).is_file():
                missing.append(csv_file)
        if missing:
            raise FileNotFoundError(
                "Decision Trigger Engine is missing mapped CSV dataset(s): "
                + ", ".join(sorted(set(missing)))
            )

    def csv_path(self, key: str) -> Path:
        item = self._mapping.get(key)
        if item is None:
            raise KeyError(f"Unknown Decision Trigger dataset key: {key}")
        filename = item.get("csv_file", "")
        if not filename:
            raise KeyError(f"No CSV file is mapped for Decision Trigger dataset: {key}")
        return self.data_dir / filename

    def supabase_table(self, key: str) -> str:
        item = self._mapping.get(key)
        if item is None:
            raise KeyError(f"Unknown Decision Trigger dataset key: {key}")
        table = item.get("supabase_table", "")
        if not table:
            raise KeyError(f"No Supabase table is mapped for Decision Trigger dataset: {key}")
        return table

    def read(self, key: str) -> pd.DataFrame:
        """Return a fresh dataframe from the configured data source."""

        if self.source == "csv":
            path = self.csv_path(key)
            if not path.is_file():
                raise FileNotFoundError(f"Mapped Decision Trigger CSV was not found: {path}")
            return pd.read_csv(path)

        return self._read_supabase(key)

    def _read_supabase(self, key: str) -> pd.DataFrame:
        table_name = self.supabase_table(key)
        try:
            client = self.client_factory()  # type: ignore[misc]
            rows: list[dict[str, Any]] = []
            start = 0

            while True:
                query = client.table(table_name).select("*")
                # Supabase/PostgREST clients support range(). Keeping the
                # fallback makes unit tests and compatible clients simple.
                if hasattr(query, "range"):
                    response = query.range(start, start + self.page_size - 1).execute()
                else:
                    response = query.execute()
                batch = list(getattr(response, "data", None) or [])
                rows.extend(batch)

                if not hasattr(query, "range") or len(batch) < self.page_size:
                    break
                start += self.page_size

            frame = pd.DataFrame(rows)
            return self._normalize_supabase_columns(key, frame)
        except Exception as exc:
            raise RuntimeError(
                f"Could not read Decision Trigger dataset '{key}' from Supabase "
                f"table '{table_name}'."
            ) from exc


    @staticmethod
    def _column_token(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    def _normalize_supabase_columns(
        self,
        key: str,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        """Accept either original CSV-style or normal Postgres snake_case columns.

        Supabase migrations often turn ``Employee_ID`` into ``employee_id``.
        When the mapped CSV schema is available locally, normalize equivalent
        names back to the original schema expected by the existing HR logic.
        No data values are changed.
        """

        if frame.empty and not len(frame.columns):
            return frame

        try:
            schema_path = self.csv_path(key)
        except KeyError:
            return frame
        if not schema_path.is_file():
            return frame

        expected = list(pd.read_csv(schema_path, nrows=0).columns)
        expected_by_token: dict[str, list[str]] = {}
        for column in expected:
            expected_by_token.setdefault(self._column_token(str(column)), []).append(str(column))

        rename: dict[str, str] = {}
        for actual in frame.columns:
            token = self._column_token(str(actual))
            candidates = expected_by_token.get(token, [])
            if len(candidates) == 1 and str(actual) != candidates[0]:
                rename[str(actual)] = candidates[0]

        return frame.rename(columns=rename)

    @contextmanager
    def successor_data_dir(self) -> Iterator[Path]:
        """Yield CSV-shaped input for the unchanged successor scoring pipeline.

        CSV mode yields the existing Data folder directly. Supabase mode writes
        only the successor input tables to a temporary directory, allowing the
        Decision Trigger Engine to reuse the exact current deterministic
        successor scoring/ranking implementation after migration.
        """

        if self.source == "csv":
            yield self.data_dir
            return

        with TemporaryDirectory(prefix="hr-dte-successor-") as temp:
            temp_path = Path(temp)
            for key in SUCCESSOR_DATASET_KEYS:
                frame = self.read(key)
                filename = self.csv_path(key).name
                frame.to_csv(temp_path / filename, index=False)
            yield temp_path

    def describe(self) -> dict[str, Any]:
        """Small diagnostics payload useful for logs/tests without exposing secrets."""

        return {
            "source": self.source,
            "source_map": str(self.source_map_path),
            "mapped_dataset_count": len(self._mapping),
        }
