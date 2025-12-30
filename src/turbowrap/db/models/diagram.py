"""Mermaid diagram storage model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from turbowrap.db.base import Base


class MermaidDiagram(Base):
    """Stores generated Mermaid diagrams for agents and documents."""

    __tablename__ = "mermaid_diagrams"

    # Use document_key as primary key (agent name or doc path)
    document_key = Column(String(255), primary_key=True)
    mermaid_code = Column(Text, nullable=False)
    diagram_type = Column(String(50), default="flowchart")  # flowchart, sequence, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<MermaidDiagram {self.document_key}>"
