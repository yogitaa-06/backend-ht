"""Compatibility imports for security persistence."""

from app.security.repository import IpRuleRepository, SecurityAuditRepository

__all__ = ["IpRuleRepository", "SecurityAuditRepository"]
