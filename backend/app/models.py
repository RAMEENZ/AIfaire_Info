import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geometry
from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    auteur: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    date_publication: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_evenement: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    categorie: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    gravite: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    lieu_nom: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    lieu_code_insee: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    lieu_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lieu_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lieu_niveau: Mapped[str] = mapped_column(String(32), nullable=False, default="national")
    lieu_confiance_geo: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    geom: Mapped[Optional[object]] = mapped_column(
        Geometry("POINT", srid=4326), nullable=True
    )

    resume_ia: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(ARRAY(String), nullable=False, server_default="{}", default=list)
    cluster_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    score_confiance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_events_date_publication", "date_publication"),
        Index("ix_events_source_gravite", "source", "gravite"),
        Index("ix_events_gravite_date", "gravite", "date_publication"),
        Index("ix_events_geom", "geom", postgresql_using="gist"),
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} source={self.source} titre={self.titre[:40]}>"


class ConnectorStatus(Base):
    __tablename__ = "connector_status"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Dernier run sans erreur (fetch réussi). Permet de distinguer un connecteur
    # qui n'a jamais fonctionné d'un connecteur momentanément en panne.
    last_success: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Nombre de runs consécutifs en échec (remis à 0 dès qu'un fetch réussit).
    # Distingue un raté transitoire (→ « dégradé ») d'une panne chronique (→ « erreur »).
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
