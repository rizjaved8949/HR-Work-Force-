from __future__ import annotations

import re
from typing import Any

from successor_service.repositories.csv_store import CSVDataStore
from successor_service.utils.serialization import clean_record


_EMPLOYEE_ID_PATTERN = re.compile(
    r"\bEMP[- ]?\d{1,6}\b",
    flags=re.IGNORECASE,
)


def normalize_employee_id(value: str) -> str:
    compact = (
        value.strip()
        .upper()
        .replace("-", "")
        .replace(" ", "")
    )

    if not compact.startswith("EMP"):
        raise ValueError(
            "Employee ID must start with EMP."
        )

    digits = compact[3:]

    if not digits.isdigit():
        raise ValueError(
            f"Invalid employee ID: {value}"
        )

    return f"EMP{int(digits):03d}"


def _normalize_text(value: str) -> str:
    return " ".join(
        re.sub(
            r"[^a-z0-9 ]+",
            " ",
            value.lower(),
        ).split()
    )


class EmployeeResolverTool:
    """
    Resolves an employee using:

    1. Employee ID only
    2. Employee name only
    3. Employee ID and name together

    When both are supplied, both must identify
    the same employee.
    """

    name = "employee_resolver_tool"

    def __init__(
        self,
        store: CSVDataStore,
    ) -> None:
        self.store = store

    def run(
        self,
        *,
        message: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
    ) -> dict:
        normalized_id: str | None = None

        if employee_id:
            try:
                normalized_id = normalize_employee_id(
                    employee_id
                )
            except ValueError as error:
                return {
                    "status": "invalid_reference",
                    "message": str(error),
                    "matches": [],
                }

        # ID and name both supplied
        if normalized_id and employee_name:
            profile = self._get_profile_by_id(
                normalized_id
            )

            if profile is None:
                return {
                    "status": "not_found",
                    "message": (
                        f"Employee ID {normalized_id} "
                        "dataset mein nahi mili."
                    ),
                    "matches": [],
                }

            name_matches = self._search_name(
                employee_name
            )

            matching_ids = {
                row["Employee_ID"]
                for row in name_matches
            }

            if normalized_id not in matching_ids:
                return {
                    "status": "identifier_mismatch",
                    "message": (
                        f"Employee ID {normalized_id} "
                        f"aur employee name "
                        f"'{employee_name}' same employee "
                        "ko identify nahi karte."
                    ),
                    "matches": [
                        {
                            "employee_id": (
                                profile["Employee_ID"]
                            ),
                            "employee_name": (
                                profile["Employee_Name"]
                            ),
                            "department": (
                                profile["Department"]
                            ),
                            "position_title": (
                                profile["Position_Title"]
                            ),
                        },
                        *[
                            {
                                "employee_id": (
                                    row["Employee_ID"]
                                ),
                                "employee_name": (
                                    row["Employee_Name"]
                                ),
                                "department": (
                                    row["Department"]
                                ),
                                "position_title": (
                                    row["Position_Title"]
                                ),
                            }
                            for row in name_matches[:5]
                            if row["Employee_ID"]
                            != normalized_id
                        ],
                    ],
                }

            return {
                "status": "resolved",
                "source": (
                    "explicit_employee_id_and_name"
                ),
                "profile": profile,
                "matches": [],
            }

        # Employee ID only
        if normalized_id:
            profile = self._get_profile_by_id(
                normalized_id
            )

            if profile is None:
                return {
                    "status": "not_found",
                    "message": (
                        f"Employee ID {normalized_id} "
                        "dataset mein nahi mili."
                    ),
                    "matches": [],
                }

            return {
                "status": "resolved",
                "source": "explicit_employee_id",
                "profile": profile,
                "matches": [],
            }

        # Legacy message support
        if message:
            match = _EMPLOYEE_ID_PATTERN.search(
                message
            )

            if match:
                try:
                    message_id = normalize_employee_id(
                        match.group(0)
                    )
                except ValueError as error:
                    return {
                        "status": "invalid_reference",
                        "message": str(error),
                        "matches": [],
                    }

                profile = self._get_profile_by_id(
                    message_id
                )

                if profile is None:
                    return {
                        "status": "not_found",
                        "message": (
                            f"Employee ID {message_id} "
                            "dataset mein nahi mili."
                        ),
                        "matches": [],
                    }

                return {
                    "status": "resolved",
                    "source": (
                        "employee_id_from_message"
                    ),
                    "profile": profile,
                    "matches": [],
                }

        # Employee name only
        name_query = (
            employee_name.strip()
            if employee_name
            else None
        )

        if not name_query and message:
            name_query = (
                self._detect_full_name_in_message(
                    message
                )
            )

        if not name_query:
            return {
                "status": "needs_clarification",
                "message": (
                    "Employee ID, complete employee "
                    "name, ya dono dein."
                ),
                "matches": [],
            }

        matches = self._search_name(
            name_query
        )

        if len(matches) == 1:
            return {
                "status": "resolved",
                "source": (
                    "explicit_employee_name"
                    if employee_name
                    else "employee_name_from_message"
                ),
                "profile": matches[0],
                "matches": [],
            }

        if not matches:
            return {
                "status": "not_found",
                "message": (
                    f"'{name_query}' naam ka employee "
                    "dataset mein nahi mila."
                ),
                "matches": [],
            }

        return {
            "status": "ambiguous",
            "message": (
                f"'{name_query}' se multiple "
                "employees mile. Complete name ya "
                "Employee ID select karein."
            ),
            "matches": [
                {
                    "employee_id": (
                        row["Employee_ID"]
                    ),
                    "employee_name": (
                        row["Employee_Name"]
                    ),
                    "department": (
                        row["Department"]
                    ),
                    "position_title": (
                        row["Position_Title"]
                    ),
                }
                for row in matches[:10]
            ],
        }

    def _get_profile_by_id(
        self,
        employee_id: str,
    ) -> dict | None:
        try:
            return self.store.one(
                "employee_profile",
                "Employee_ID",
                employee_id,
                "Employee",
            )
        except Exception:
            return None

    def _detect_full_name_in_message(
        self,
        message: str,
    ) -> str | None:
        normalized_message = _normalize_text(
            message
        )

        frame = self.store.table(
            "employee_profile"
        )

        found: list[tuple[int, str]] = []

        for employee_name in frame[
            "Employee_Name"
        ].astype(str):
            normalized_name = _normalize_text(
                employee_name
            )

            if (
                normalized_name
                and normalized_name
                in normalized_message
            ):
                found.append(
                    (
                        len(normalized_name),
                        employee_name,
                    )
                )

        if not found:
            return None

        found.sort(reverse=True)
        return found[0][1]

    def _search_name(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        normalized_query = _normalize_text(
            query
        )

        if not normalized_query:
            return []

        frame = self.store.table(
            "employee_profile"
        ).copy()

        frame["_normalized_name"] = (
            frame["Employee_Name"]
            .astype(str)
            .map(_normalize_text)
        )

        exact = frame[
            frame["_normalized_name"]
            == normalized_query
        ]

        if not exact.empty:
            return [
                clean_record(row)
                for row in exact.drop(
                    columns=["_normalized_name"]
                ).to_dict("records")
            ]

        partial = frame[
            frame["_normalized_name"].str.contains(
                normalized_query,
                regex=False,
            )
        ]

        return [
            clean_record(row)
            for row in partial.drop(
                columns=["_normalized_name"]
            ).to_dict("records")
        ]