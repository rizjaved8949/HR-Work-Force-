"""Step-3 semantic mapping layer for current HR data.

This package is read-only. It profiles and validates current source data against
HR Ontology v1; it does not change existing service runtime paths.
"""

from .service import CURRENT_MAPPING_SERVICE

__all__ = ["CURRENT_MAPPING_SERVICE"]
