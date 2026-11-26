from datetime import datetime

from pydantic import BaseModel, Field


class EmployeeDatasetRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    size: int = Field(ge=5_000, le=500_000)
    seed: int = Field(ge=0, le=2**32 - 1)
    initial_epsilon: float = Field(default=10.0, gt=0, le=100)


class DatasetResponse(BaseModel):
    id: int
    name: str
    description: str
    source_type: str
    table_name: str
    record_count: int
    sensitivity: str
    created_at: datetime
    owner: str | None = None
    access_roles: list[str] = Field(default_factory=list)
    columns: list[dict] = Field(default_factory=list)


class DatasetListResponse(BaseModel):
    items: list[DatasetResponse]
