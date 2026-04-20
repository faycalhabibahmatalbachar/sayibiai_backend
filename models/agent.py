"""Schémas Pydantic pour le mode agent SAYIBI (réponses JSON structurées)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentTurnRequest(BaseModel):
    """Requête utilisateur + contexte multi-tours."""

    message: str = Field(..., min_length=1, max_length=8000)
    """Dernier message utilisateur (ou confirmation « oui » / « annule »)."""

    pending: Optional[Dict[str, Any]] = None
    """État précédent : payload en attente (confirm_needed, clarify_contact, etc.)."""

    contact_search_results: Optional[List[Dict[str, Any]]] = None
    """Résultats locaux de search_contacts (Flutter / Android)."""

    permission_state: Optional[Dict[str, bool]] = None
    """Ex. {\"contacts\": true, \"sms\": false}."""

    memory_context: Optional[str] = None
    """Résumé mémoire fourni par le client (historique SMS/actions)."""


class AgentLogRequest(BaseModel):
    action_type: str
    contact_id: Optional[str] = None
    phone_masked: Optional[str] = None
    message_preview: Optional[str] = None
    status: str = "success"
    ambiguity_type: Optional[str] = "none"
    confidence: Optional[float] = None
    client_meta: Optional[Dict[str, Any]] = None


class ContactResolutionBody(BaseModel):
    query: str
    contact_id_chosen: str
    display_name_snapshot: Optional[str] = None
    resolution_type: str = "user_picked"


class AgentMemorySummaryQuery(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class AgentStructuredResponse(BaseModel):
    """Réponse obligatoire du modèle (souplesse sur payload)."""

    thinking: str = ""
    action: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    next_steps: List[str] = Field(default_factory=list)
    message_to_user: str = ""
    confidence: float = 0.0
    ambiguities: List[Any] = Field(default_factory=list)
