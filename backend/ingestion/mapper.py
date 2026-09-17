"""Deterministic ontology mapping suggestions for unknown organization schemas.

This module deliberately suggests; it never silently approves mappings.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .models import (
    ColumnMappingProposal,
    MappingCandidate,
    SourceSchemaProfile,
)


_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str) -> str:
    text = _CAMEL.sub(r"\1 \2", str(value)).lower()
    return "".join(_NON_ALNUM.sub(" ", text).split())


def token_set(value: str) -> set[str]:
    text = _CAMEL.sub(r"\1 \2", str(value)).lower()
    return {item for item in _NON_ALNUM.sub(" ", text).split() if item}


def _type_compatible(observed: str, semantic: str) -> bool | None:
    if observed in {"empty", "string"}:
        return None if observed == "empty" else semantic == "string"
    if semantic == "string":
        return True
    if semantic == "decimal":
        return observed in {"integer", "decimal"}
    if semantic == "integer":
        return observed == "integer"
    if semantic == "boolean":
        return observed in {"boolean", "boolean_like", "integer"}
    if semantic == "date":
        return observed in {"date", "datetime", "date_like"}
    if semantic in {"datetime", "timestamp"}:
        return observed in {"datetime", "date", "date_like"}
    return None


class OntologyMappingSuggester:
    def __init__(self, registry: OntologyRegistry = DEFAULT_REGISTRY) -> None:
        self.registry = registry

    def _candidate_score(self, source: str, prop) -> tuple[float, str]:
        source_norm = normalize_name(source)
        prop_norm = normalize_name(prop.name)
        aliases = [str(item) for item in prop.current_source_fields]
        alias_norms = [normalize_name(item) for item in aliases]

        if source == prop.name:
            return 1.0, "exact_property_name"
        if source_norm == prop_norm:
            return 0.995, "normalized_property_name"
        if source in aliases:
            return 0.99, "exact_confirmed_source_alias"
        if source_norm in alias_norms:
            return 0.985, "normalized_confirmed_source_alias"

        source_tokens = token_set(source)
        best = SequenceMatcher(None, source_norm, prop_norm).ratio()
        strategy = "fuzzy_property_name"
        for alias, alias_norm in zip(aliases, alias_norms):
            score = SequenceMatcher(None, source_norm, alias_norm).ratio()
            if score > best:
                best = score
                strategy = f"fuzzy_confirmed_alias:{alias}"

        prop_tokens = token_set(prop.name)
        if source_tokens and prop_tokens:
            overlap = len(source_tokens & prop_tokens) / max(len(source_tokens | prop_tokens), 1)
            if overlap >= 0.5:
                boosted = min(0.92, 0.70 + 0.22 * overlap)
                if boosted > best:
                    best = boosted
                    strategy = "token_overlap"
        return best, strategy

    def propose_column(
        self,
        source_column: str,
        observed_type: str,
        *,
        limit: int = 5,
        minimum_confidence: float = 0.58,
    ) -> ColumnMappingProposal:
        candidates: list[MappingCandidate] = []
        for entity in self.registry.list_entities():
            for prop in entity.properties:
                score, strategy = self._candidate_score(source_column, prop)
                if score < minimum_confidence:
                    continue
                compatible = _type_compatible(observed_type, prop.data_type)
                adjusted = score
                if compatible is False:
                    adjusted = max(0.0, score - 0.12)
                candidates.append(
                    MappingCandidate(
                        ontology_path=f"{entity.name}.{prop.name}",
                        entity_type=entity.name,
                        property_name=prop.name,
                        match_strategy=strategy,
                        confidence=round(adjusted, 4),
                        semantic_status=prop.semantic_status,
                        type_compatible=compatible,
                    )
                )
        candidates.sort(key=lambda item: (-item.confidence, item.ontology_path))
        candidates = candidates[:limit]
        recommended = candidates[0] if candidates else None
        # Human approval is mandatory even for exact matches. Recommendation only
        # reduces manual search; it does not establish semantic truth.
        return ColumnMappingProposal(
            source_column=source_column,
            observed_type=observed_type,
            candidates=candidates,
            recommended_ontology_path=(recommended.ontology_path if recommended else None),
            recommendation_confidence=(recommended.confidence if recommended else 0.0),
            review_required=True,
        )

    def propose_schema(self, profile: SourceSchemaProfile) -> list[ColumnMappingProposal]:
        return [
            self.propose_column(column.name, column.observed_type)
            for column in profile.columns
        ]

    def relationship_candidates(self, entity_types: set[str]) -> list[dict]:
        result: list[dict] = []
        for rel in self.registry.load().relationships:
            if rel.source in entity_types and rel.target in entity_types:
                result.append(
                    {
                        "source_entity_type": rel.source,
                        "relation_type": rel.relation,
                        "target_entity_type": rel.target,
                        "cardinality": rel.cardinality,
                        "semantic_status": rel.semantic_status,
                        "review_required": True,
                    }
                )
        return result


DEFAULT_MAPPING_SUGGESTER = OntologyMappingSuggester()
