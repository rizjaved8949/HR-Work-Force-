from __future__ import annotations

import pandas as pd

from successor_service.repositories.csv_store import CSVDataStore
from successor_service.utils.serialization import clean_record


class CandidatePoolTool:
    name = "candidate_pool_tool"

    def __init__(self, store: CSVDataStore, config: dict) -> None:
        self.store = store
        self.config = config

    def run(self, target_profile: dict) -> list[dict]:
        frame = self.store.table("employee_profile").copy()
        target_id = target_profile["Employee_ID"]
        department = target_profile["Department"]

        base = frame[
            (frame["Employee_Status"].astype(str).str.lower() == "active")
            & (frame["Employee_ID"] != target_id)
        ].copy()

        allowed = ["Eligible"]
        if self.config["candidate_pool"].get("include_development_hold", True):
            allowed.append("Development / Hold")

        base = base[base["Candidate_Base_Eligibility"].isin(allowed)]

        primary = base[base["Department"] == department].copy()
        primary["Candidate_Pool_Source"] = "Same Department"

        minimum = int(
            self.config["candidate_pool"].get(
                "minimum_pool_before_fallback", 8
            )
        )
        use_fallback = bool(
            self.config["candidate_pool"].get(
                "organization_fallback", True
            )
        )

        if use_fallback and len(primary) < minimum:
            fallback = base[base["Department"] != department].copy()
            fallback["Candidate_Pool_Source"] = "Organization Fallback"
            combined = pd.concat([primary, fallback], ignore_index=True)
        else:
            combined = primary

        return [
            clean_record(record)
            for record in combined.to_dict("records")
        ]
