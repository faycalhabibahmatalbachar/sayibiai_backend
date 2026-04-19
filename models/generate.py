"""Schémas pour la génération de fichiers."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CVPersonalInfo(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None


class CVExperience(BaseModel):
    title: str
    company: str
    start: str
    end: Optional[str] = None
    description: Optional[str] = None


class CVEducation(BaseModel):
    degree: str
    school: str
    year: Optional[str] = None


class GenerateCVRequest(BaseModel):
    personal_info: CVPersonalInfo
    experience: List[CVExperience] = Field(default_factory=list)
    education: List[CVEducation] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    language: str = "fr"


class GenerateLetterRequest(BaseModel):
    type: str = "lettre_motivation"
    context: str
    recipient: Optional[str] = None
    tone: str = "professionnel"
    language: str = "fr"


class GenerateReportRequest(BaseModel):
    topic: str
    sections: List[str] = Field(default_factory=list)
    data: Optional[Dict[str, Any]] = None
    language: str = "fr"


class GenerateExcelRequest(BaseModel):
    title: str
    columns: List[str]
    data_description: str
    language: str = "fr"


class GenerateFromChatRequest(BaseModel):
    session_id: str
    output_type: str = "report"  # report, cv, letter
