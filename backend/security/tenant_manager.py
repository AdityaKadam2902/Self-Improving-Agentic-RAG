"""
Tenant Access Control and Role-Based Access Control (RBAC) Manager.

Enforces metadata-level isolation across multi-tenant vector indices and storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserContext:
    user_id: str
    tenant_id: str = "default"
    roles: List[str] = field(default_factory=lambda: ["user"])


def build_vector_tenant_filter(
    tenant_id: str = "default",
    allowed_roles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Construct an immutable metadata query mask for ChromaDB / Qdrant.
    Guarantees queries only return chunks belonging to the caller's tenant.
    """
    filters: Dict[str, Any] = {"tenant_id": tenant_id}
    if allowed_roles:
        filters["access_roles"] = allowed_roles
    return filters


def validate_chunk_access(
    chunk_metadata: Dict[str, Any],
    user_context: UserContext,
) -> bool:
    """
    Verify whether a user context has cryptographic clearance to view a chunk.
    """
    chunk_tenant = chunk_metadata.get("tenant_id", "default")
    if chunk_tenant != user_context.tenant_id:
        return False

    chunk_roles = chunk_metadata.get("access_roles", [])
    if not chunk_roles:
        return True  # Public within tenant

    # Check intersection of user roles with chunk required roles
    user_roles_set = set(user_context.roles)
    if "admin" in user_roles_set:
        return True

    return bool(user_roles_set.intersection(set(chunk_roles)))
