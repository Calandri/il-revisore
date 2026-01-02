"""Mermaid diagram storage model."""

from sqlalchemy import Column, String, Text

from turbowrap.db.base import Base

from .base import TZDateTime, now_utc


class MermaidDiagram(Base):
    """Stores generated Mermaid diagrams for agents and documents."""

    __tablename__ = "mermaid_diagrams"
    __table_args__ = {"extend_existing": True}

    # Use document_key as primary key (agent name or doc path)
    document_key = Column(String(255), primary_key=True)
    mermaid_code = Column(Text, nullable=False)
    diagram_type = Column(String(50), default="flowchart")  # flowchart, sequence, etc.
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    def __repr__(self) -> str:
        return f"<MermaidDiagram {self.document_key}>"
