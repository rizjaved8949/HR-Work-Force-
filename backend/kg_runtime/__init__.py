"""Knowledge-Graph-only runtime compatibility layer."""
from .config import KGRuntimeConfig
from .materializer import ensure_materialized_data_dir

__all__ = ["KGRuntimeConfig", "ensure_materialized_data_dir"]
