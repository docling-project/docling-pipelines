"""The ededup admission table, independently owned by the operator."""

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel


class EdedupHashPostgresModel(SQLModel, table=True):  # type: ignore[call-arg]
    """Run-scoped admissions, retained independently of source deletion."""

    __tablename__ = "hashes"
    __table_args__ = {"extend_existing": True}

    job_id: str = Field(sa_column=Column(String, primary_key=True))
    node_id: str = Field(sa_column=Column(String, primary_key=True))
    job_run_id: str = Field(sa_column=Column(String, primary_key=True))
    hash_value: str = Field(sa_column=Column(String, primary_key=True))
    doc_id: str = Field(sa_column=Column(String, nullable=False))
