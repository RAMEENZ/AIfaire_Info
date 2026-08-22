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
    # Pagination : rang du premier élément renvoyé et présence d'une suite.
    # Permet au client de charger le fil par tranches au lieu des 500
    # événements historiques (451 Ko de JSON, ~90 000 px de DOM).
    offset: int = 0
    has_more: bool = False


class ConnectorStatusSchema(BaseModel):
    name: str
    last_run: Optional[datetime] = None
    last_error: Optional[str] = None
    last_count: Optional[int] = None
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    status: str

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    connectors: List[ConnectorStatusSchema]
    checked_at: datetime
    next_ingest_at: Optional[datetime] = None
    # Rythme de collecte, exposé pour que l'interface puisse l'afficher sans
    # le recopier. Le recopier en dur côté frontend le ferait diverger dès la
    # première modification d'INGEST_HOURS, sans que rien ne le signale.
    ingest_hours: List[int] = []
    ingest_timezone: str = ""
    hourly_alerts: bool = False
