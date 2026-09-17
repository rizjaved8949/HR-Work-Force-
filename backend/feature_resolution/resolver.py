"""Generic ontology-path feature resolver with explicit missing-data policy."""
from __future__ import annotations

from datetime import date
from typing import Any

from semantic.models import EmployeeContext

from .derivations import DEFAULT_DERIVATIONS, FeatureDerivationRegistry
from .models import (
    FeatureContract,
    FeatureResolutionReport,
    MissingPolicy,
    ResolvedFeature,
    ResolutionMethod,
    ResolutionStatus,
)
from .providers import SemanticValueProvider


class FeatureResolver:
    def __init__(self, derivations: FeatureDerivationRegistry = DEFAULT_DERIVATIONS) -> None:
        self.derivations = derivations

    def resolve(
        self,
        contract: FeatureContract,
        *,
        provider: SemanticValueProvider,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        employee_context: EmployeeContext | None = None,
        as_of_date: date | None = None,
        strict_missing: bool = False,
    ) -> FeatureResolutionReport:
        results: list[ResolvedFeature] = []
        report_warnings: list[str] = []

        for spec in contract.ordered_features():
            provided = provider.get(spec.ontology_path)
            warning_codes: list[str] = []
            notes = list(provided.notes)

            if spec.semantic_status != "confirmed":
                warning_codes.append(f"semantic_status_{spec.semantic_status}")
                report_warnings.append(
                    f"{spec.ontology_path} has ontology semantic_status={spec.semantic_status}; "
                    "the current value may be passed through but Step 8 will not invent normalization."
                )

            if provided.present:
                results.append(
                    ResolvedFeature(
                        order=spec.order,
                        feature_name=spec.feature_name,
                        ontology_path=spec.ontology_path,
                        model_type=spec.model_type,
                        unit=spec.unit,
                        missing_policy=spec.missing_policy,
                        semantic_status=spec.semantic_status,
                        method=ResolutionMethod.DIRECT,
                        value=provided.value,
                        source_reference_ids=list(provided.source_reference_ids),
                        warning_codes=warning_codes,
                        notes=notes,
                    )
                )
                continue

            derivation = self.derivations.derive(
                spec.ontology_path,
                provider=provider,
                employee_context=employee_context,
                as_of_date=as_of_date,
            )
            if derivation.resolved:
                notes.extend(derivation.notes)
                results.append(
                    ResolvedFeature(
                        order=spec.order,
                        feature_name=spec.feature_name,
                        ontology_path=spec.ontology_path,
                        model_type=spec.model_type,
                        unit=spec.unit,
                        missing_policy=spec.missing_policy,
                        semantic_status=spec.semantic_status,
                        method=ResolutionMethod.DERIVED,
                        value=derivation.value,
                        source_reference_ids=list(derivation.source_reference_ids),
                        derivation_rule=derivation.rule_id,
                        warning_codes=warning_codes,
                        notes=notes,
                    )
                )
                continue
            if derivation.rule_id:
                notes.extend(derivation.notes)

            has_default, default_value, default_rule = self.derivations.safe_default(spec.ontology_path)
            if spec.missing_policy == MissingPolicy.SAFE_DEFAULT and has_default:
                results.append(
                    ResolvedFeature(
                        order=spec.order,
                        feature_name=spec.feature_name,
                        ontology_path=spec.ontology_path,
                        model_type=spec.model_type,
                        unit=spec.unit,
                        missing_policy=spec.missing_policy,
                        semantic_status=spec.semantic_status,
                        method=ResolutionMethod.DEFAULTED,
                        value=default_value,
                        derivation_rule=default_rule,
                        warning_codes=warning_codes + ["approved_safe_default_used"],
                        notes=notes + ["Value came from an explicitly approved Step-8 safe-default rule."],
                    )
                )
                continue

            effective_policy = spec.missing_policy
            if strict_missing and spec.required:
                effective_policy = MissingPolicy.CRITICAL
            if effective_policy == MissingPolicy.SAFE_DEFAULT and not has_default:
                effective_policy = MissingPolicy.CRITICAL
                notes.append("Safe-default policy was requested but no approved default exists.")

            results.append(
                ResolvedFeature(
                    order=spec.order,
                    feature_name=spec.feature_name,
                    ontology_path=spec.ontology_path,
                    model_type=spec.model_type,
                    unit=spec.unit,
                    missing_policy=effective_policy,
                    semantic_status=spec.semantic_status,
                    method=ResolutionMethod.MISSING,
                    value=None,
                    source_reference_ids=list(provided.source_reference_ids),
                    derivation_rule=derivation.rule_id,
                    warning_codes=warning_codes,
                    notes=notes,
                )
            )

        direct_count = sum(item.method == ResolutionMethod.DIRECT for item in results)
        derived_count = sum(item.method == ResolutionMethod.DERIVED for item in results)
        defaulted_count = sum(item.method == ResolutionMethod.DEFAULTED for item in results)
        missing = [item for item in results if item.method == ResolutionMethod.MISSING]
        critical_missing = [item for item in missing if item.missing_policy == MissingPolicy.CRITICAL]
        optional_missing = [item for item in missing if item.missing_policy == MissingPolicy.OPTIONAL]
        model_native_missing = [
            item for item in missing if item.missing_policy == MissingPolicy.MODEL_NATIVE
        ]
        warning_count = sum(len(item.warning_codes) for item in results)

        if critical_missing:
            status = ResolutionStatus.BLOCKED
        elif missing:
            status = ResolutionStatus.DEGRADED
        elif warning_count:
            status = ResolutionStatus.READY_WITH_WARNINGS
        else:
            status = ResolutionStatus.READY

        # Preserve first occurrence order while eliminating duplicate messages.
        report_warnings = list(dict.fromkeys(report_warnings))

        return FeatureResolutionReport(
            service=contract.service,
            contract_name=contract.contract_name,
            tenant_id=tenant_id,
            subject_id=subject_id,
            status=status,
            feature_count=len(results),
            direct_count=direct_count,
            derived_count=derived_count,
            defaulted_count=defaulted_count,
            missing_count=len(missing),
            critical_missing_count=len(critical_missing),
            optional_missing_count=len(optional_missing),
            model_native_missing_count=len(model_native_missing),
            warning_count=warning_count,
            features=results,
            report_warnings=report_warnings,
        )


DEFAULT_FEATURE_RESOLVER = FeatureResolver()
