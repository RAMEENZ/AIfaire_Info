from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class EventBase(BaseModel):
    id: str
    source: str
    source_url: str
    titre: str
    auteur: Optional[str] = None
    date_publication: datetime
    date_evenement: Optional[datetime] = None
    categorie: str
    gravite: int = Field(ge=0, le=3)
    lieu_nom: Optional[str] = None
    lieu_code_insee: Optional[str] = None
    lieu_lat: Optional[float] = None
    lieu_lon: Optional[float] = None
    lieu_niveau: str
    lieu_confiance_geo: float = Field(ge=0.0, le=1.0)
    resume_ia: Optional[str] = None
    tags: List[str] = []
    cluster_id: Optional[str] = None
    score_confiance: float = Field(ge=0.0, le=1.0)
    created_at: datetime

    model_config = {"from_attributes": True}


class EventDetail(EventBase):
    pass


class EventList(BaseModel):
    events: List[EventBase]
    total: int
    generated_at: datetime


class ConnectorStatusSchema(BaseModel):
    name: str
    last_run: Optional[datetime] = None
    last_error: Optional[str] = None
    last_count: Optional[int] = None
    status: str

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    connectors: List[ConnectorStatusSchema]
    checked_at: datetime
    next_ingest_at: Optional[datetime] = None
