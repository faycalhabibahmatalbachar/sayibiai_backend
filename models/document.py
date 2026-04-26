"""Schémas pour les documents."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DocumentAskRequest(BaseModel):
    doc_id: str
    question: str


class DocumentSummarizeRequest(BaseModel):
    doc_id: str
    format: Literal["bullets", "paragraph", "key_points"] = "bullets"


class DocumentAskResponse(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
