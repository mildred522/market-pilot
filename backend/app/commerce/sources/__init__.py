"""Data-source adapter contracts for the commerce domain."""

from app.commerce.sources.base import CommerceSourceAdapter
from app.commerce.sources.olist import OlistSourceAdapter

__all__ = ["CommerceSourceAdapter", "OlistSourceAdapter"]
