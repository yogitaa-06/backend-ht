from typing import cast

from sqlalchemy import Table, UniqueConstraint

from app.domain.jobs import CanonicalJob, Company, JobSourceObservation


def test_canonical_tables_use_distinct_platform_concepts() -> None:
    assert Company.__tablename__ == "companies"
    assert CanonicalJob.__tablename__ == "jobs"
    assert JobSourceObservation.__tablename__ == "job_sources"
    assert "source" not in CanonicalJob.__table__.columns
    assert JobSourceObservation.__table__.columns.job_id.foreign_keys


def test_source_identity_has_a_database_unique_constraint() -> None:
    identities = {
        tuple(column.name for column in constraint.columns)
        for constraint in cast(Table, JobSourceObservation.__table__).constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("source", "source_job_id") in identities


def test_company_resolution_is_exact_and_database_enforced() -> None:
    identities = {
        tuple(column.name for column in constraint.columns)
        for constraint in cast(Table, Company.__table__).constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("normalized_name",) in identities
