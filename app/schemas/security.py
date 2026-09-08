"""Validated administrator contracts for IP rules and safe audit views."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.security import SecurityAuditEventType
from app.security.ip import normalize_network


class IpRuleCreate(BaseModel):
    cidr: str
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @field_validator("cidr")
    @classmethod
    def validate_cidr(cls, value: str) -> str:
        try:
            return str(normalize_network(value))
        except ValueError:
            raise ValueError("must be a valid IPv4 or IPv6 CIDR") from None


class IpRuleUpdate(BaseModel):
    cidr: str | None = None
    label: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("cidr")
    @classmethod
    def validate_cidr(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(normalize_network(value))
        except ValueError:
            raise ValueError("must be a valid IPv4 or IPv6 CIDR") from None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class IpRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cidr: str
    label: str
    description: str | None
    enabled: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class IpRulePage(BaseModel):
    items: list[IpRuleResponse]
    total: int
    offset: int
    limit: int


class CurrentIpResponse(BaseModel):
    ip: str | None
    emergency_bypass: bool


class SecurityAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    event_type: SecurityAuditEventType
    request_ip: str | None
    user_agent: str | None
    resource_type: str | None
    resource_id: UUID | None
    created_at: datetime


class SecurityAuditEventPage(BaseModel):
    items: list[SecurityAuditEventResponse]
    total: int
    offset: int
    limit: int
