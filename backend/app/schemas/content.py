"""
EAAWP Content Intelligence Schemas

Validation for content CRUD, generation requests, and analysis.
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

VALID_CONTENT_TYPES = {"brief", "idea", "draft", "variant", "analysis"}
VALID_STATUSES = {"draft", "review", "approved", "rejected", "archived"}
VALID_CHANNELS = {
    "email", "social_linkedin", "social_twitter", "social_instagram",
    "blog", "ad", "landing_page", "custom",
}

ContentType = Literal["brief", "idea", "draft", "variant", "analysis"]
ContentStatus = Literal["draft", "review", "approved", "rejected", "archived"]


class ContentItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content_type: ContentType = "draft"
    status: ContentStatus = "draft"
    channel: str = Field(default="", max_length=64)
    brief_json: dict[str, Any] = Field(default_factory=dict)
    body: str = Field(default="", max_length=100_000)
    campaign_id: str | None = None
    objective_id: str | None = None
    parent_id: str | None = None
    rag_sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(default="agent", max_length=128)

    @field_validator("title")
    @classmethod
    def safe_title(cls, v: str) -> str:
        for bad in (";", "--", "exec(", "eval("):
            if bad.lower() in v.lower():
                raise ValueError("Title contains forbidden pattern.")
        return v.strip()


class ContentItemUpdate(BaseModel):
    title: str | None = None
    status: ContentStatus | None = None
    channel: str | None = None
    brief_json: dict[str, Any] | None = None
    body: str | None = None
    metadata: dict[str, Any] | None = None


class ContentItemOut(BaseModel):
    id: str
    tenant_id: str
    content_type: str
    status: str
    title: str
    channel: str
    brief_json: dict[str, Any]
    body: str
    campaign_id: str | None
    objective_id: str | None
    parent_id: str | None
    rag_sources: list[str]
    analysis: dict[str, Any]
    metadata: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Generation request schemas ─────────────────────────────────────────────────

class GenerateBriefRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=500)
    target_audience: str = Field(default="", max_length=500)
    channel: str = Field(default="email", max_length=64)
    campaign_id: str | None = None
    campaign_name: str | None = None
    kpis: list[str] = Field(default_factory=list)
    tone: str = Field(default="professional", max_length=64)
    additional_context: str = Field(default="", max_length=1000)


class GenerateIdeasRequest(BaseModel):
    brief_id: str | None = None
    objective: str = Field(..., min_length=1, max_length=500)
    channel: str = Field(default="email", max_length=64)
    target_audience: str = Field(default="", max_length=500)
    n_ideas: int = Field(default=5, ge=1, le=10)
    campaign_id: str | None = None


class GenerateDraftRequest(BaseModel):
    brief_id: str | None = None
    objective: str = Field(..., min_length=1, max_length=500)
    channel: str = Field(default="email", max_length=64)
    target_audience: str = Field(default="", max_length=500)
    tone: str = Field(default="professional", max_length=64)
    cta: str = Field(default="", max_length=255)
    campaign_id: str | None = None
    max_words: int = Field(default=300, ge=50, le=2000)


class GenerateVariantsRequest(BaseModel):
    source_content_id: str = Field(..., min_length=1)
    n_variants: int = Field(default=3, ge=1, le=5)
    variation_instructions: str = Field(default="", max_length=500)


class AnalyzeContentRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    campaign_objective: str = Field(default="", max_length=500)
    target_audience: str = Field(default="", max_length=500)
    cta: str = Field(default="", max_length=255)
    channel: str = Field(default="", max_length=64)
