"""Schémas pour le chat."""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessageItem(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    language: Optional[str] = None  # fr, ar, en, auto
    model_preference: Optional[str] = None  # groq, gemini, mistral, auto, sayibi-*
    personality: Optional[str] = None
    expert_mode: Optional[bool] = False
    web_search: Optional[bool] = False
    document_id: Optional[str] = None
    create_mode: Optional[bool] = False
    create_type: Optional[str] = None  # cv | letter | report | excel


class ChatStreamRequest(ChatMessageRequest):
    pass


class ChatMessageResponse(BaseModel):
    response: str
    model_used: str
    tokens: Optional[int] = None
    session_id: str


class HistoryResponse(BaseModel):
    messages: List[dict]
    total: int
    page: int
    page_size: int
