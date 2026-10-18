from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ClusterCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    provider: Literal["AWS", "Azure", "GCP"] = "AWS"
    region: str = Field(default="us-east-1", min_length=2, max_length=64)
    trino_version: str = Field(default="455", pattern=r"^[0-9]+(?:\.[0-9]+)*$")
    worker_count: int = Field(default=2, ge=1, le=100)
    worker_cpu: str = Field(default="2", pattern=r"^[0-9]+(?:m)?$")
    worker_memory: str = Field(default="4Gi", pattern=r"^[0-9]+(?:Mi|Gi|Ti)$")
    coordinator_cpu: str = Field(default="2", pattern=r"^[0-9]+(?:m)?$")
    coordinator_memory: str = Field(default="4Gi", pattern=r"^[0-9]+(?:Mi|Gi|Ti)$")


class ScaleRequest(BaseModel):
    worker_count: int = Field(ge=1, le=100)


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)

    @field_validator("sql")
    @classmethod
    def sql_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SQL must not be blank")
        return value
