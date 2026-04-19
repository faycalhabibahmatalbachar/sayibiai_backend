"""Schémas pour la voix."""

from typing import Optional

from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = "fr"
    voice: Optional[str] = None


class TranscribeResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None
