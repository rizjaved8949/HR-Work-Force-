"""Roadmap Step 8: Feature Resolution / Missing Feature Layer."""

from .adapters import (
    DEFAULT_ATTRITION_ADAPTER,
    AttritionCatBoostAdapter,
    FeatureResolutionBlockedError,
)
from .models import (
    FeatureContract,
    FeatureResolutionReport,
    FeatureSpec,
    MissingPolicy,
    ModelInputEnvelope,
    ResolvedFeature,
    ResolutionMethod,
    ResolutionStatus,
)
from .registry import DEFAULT_FEATURE_CONTRACTS, FeatureContractRegistry
from .resolver import DEFAULT_FEATURE_RESOLVER, FeatureResolver
from .service import FeatureResolutionService

__all__ = [
    "AttritionCatBoostAdapter",
    "DEFAULT_ATTRITION_ADAPTER",
    "DEFAULT_FEATURE_CONTRACTS",
    "DEFAULT_FEATURE_RESOLVER",
    "FeatureContract",
    "FeatureContractRegistry",
    "FeatureResolutionBlockedError",
    "FeatureResolutionReport",
    "FeatureResolutionService",
    "FeatureResolver",
    "FeatureSpec",
    "MissingPolicy",
    "ModelInputEnvelope",
    "ResolvedFeature",
    "ResolutionMethod",
    "ResolutionStatus",
]
