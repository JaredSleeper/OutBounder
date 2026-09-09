from __future__ import annotations

from pydantic import BaseModel, Field


class ListCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    raw_input: str = Field(min_length=1, max_length=200_000)
    context: str = Field(default="", max_length=5000)


class ListUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=5000)


class AppendTargets(BaseModel):
    raw_input: str = Field(min_length=1, max_length=200_000)


class TargetUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    title: str | None = None
    hints: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    best_email: str | None = None
    outreach_status: str | None = Field(default=None, pattern="^(todo|drafted|sent|replied|skip)$")
    notes: str | None = None
