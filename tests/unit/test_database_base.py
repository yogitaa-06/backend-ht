from sqlalchemy import MetaData

from app.db.base import SCHEMA, Base, IdentityTimestampMixin


def test_database_schema_is_private_application_schema() -> None:
    """Application tables must live outside provider-managed schemas."""
    assert SCHEMA == "hireandtech"
    assert isinstance(Base.metadata, MetaData)
    assert Base.metadata.schema == "hireandtech"


def test_base_uses_naming_convention() -> None:
    """Constraint naming must remain deterministic for Alembic migrations."""
    convention = Base.metadata.naming_convention

    assert convention is not None
    assert convention["pk"] == "pk_%(table_name)s"
    assert convention["fk"] == ("fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s")


def test_identity_timestamp_mixin_declares_common_columns() -> None:
    """Shared persistence mixin must expose identity and audit timestamps."""
    annotations = IdentityTimestampMixin.__annotations__

    assert "id" in annotations
    assert "created_at" in annotations
    assert "updated_at" in annotations
