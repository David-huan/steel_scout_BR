from typing import Literal

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    product: str = Field(default="Stainless steel flat products and profiles", min_length=2, max_length=300)
    country: str = Field(default="Brazil", min_length=2, max_length=80)
    target_count: int = Field(default=15, ge=1, le=200)
    options: dict = Field(default_factory=dict)


class ReviewUpdate(BaseModel):
    status: Literal["new", "approved", "rejected", "needs_info"]
    note: str | None = Field(default=None, max_length=2000)


class MergeRequest(BaseModel):
    keep_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)
