"""Schémas Pydantic pour Alarmes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AlarmCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    message: Optional[str] = Field(None, max_length=2000)
    scheduled_for: datetime
    timezone: str = Field(default="Africa/Ndjamena", min_length=1, max_length=80)
    repeat_rule: Optional[str] = Field(None, max_length=120)
    delivery_channel: str = Field(default="push")
    metadata: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = Field(None, max_length=120)


class AlarmUpdateBody(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    message: Optional[str] = Field(None, max_length=2000)
    scheduled_for: Optional[datetime] = None
    timezone: Optional[str] = Field(None, min_length=1, max_length=80)
    repeat_rule: Optional[str] = Field(None, max_length=120)
    is_enabled: Optional[bool] = None
    status: Optional[str] = None
    delivery_channel: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

