"""
Models for README analysis and documentation generation.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FunctionalitySection(BaseModel):
    """Sezione: cosa fa la repository."""

    summary: str = Field(..., description="Descrizione generale (2-3 frasi)")
    main_features: list[str] = Field(default_factory=list, description="Features principali")
    use_cases: list[str] = Field(default_factory=list, description="Casi d'uso tipici")


class LogicSection(BaseModel):
    """Sezione: come funziona internamente."""

    overview: str = Field(..., description="Panoramica del flusso")
    main_flows: list[dict[str, str]] = Field(
        default_factory=list, description="Flussi principali con name e description"
    )
    key_algorithms: list[str] = Field(default_factory=list, description="Algoritmi chiave")


class StructureSection(BaseModel):
    """Sezione: organizzazione directory."""

    layers: list[dict[str, str]] = Field(
        default_factory=list, description="Layer architetturali con name e purpose"
    )
    key_modules: list[dict[str, str]] = Field(
        default_factory=list, description="Moduli chiave con name e purpose"
    )
    directory_tree: str = Field(default="", description="ASCII tree delle directory")


class CodeSection(BaseModel):
    """Sezione: tech stack e pattern."""

    language: str = Field(default="", description="Linguaggio principale")
    framework: str = Field(default="", description="Framework principale")
    patterns: list[str] = Field(default_factory=list, description="Design pattern usati")
    best_practices: list[str] = Field(default_factory=list, description="Best practices osservate")
    dependencies_summary: str = Field(default="", description="Riassunto dipendenze")


class MermaidDiagram(BaseModel):
    """Singolo diagramma Mermaid."""

    type: str = Field(..., description="Tipo: dependency|callgraph|architecture|flowchart")
    title: str = Field(..., description="Titolo del diagramma")
    code: str = Field(..., description="Codice Mermaid valido")
    description: str = Field(default="", description="Descrizione del diagramma")


class ReadmeAnalysis(BaseModel):
    """Analisi completa per README UI."""

    # Sezioni testuali
    functionality: FunctionalitySection
    logic: LogicSection
    structure: StructureSection
    code: CodeSection

    # Diagrammi
    diagrams: list[MermaidDiagram] = Field(default_factory=list)

    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generator_model: str = Field(default="gemini-flash")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReadmeAnalysis":
        """Create from dictionary."""
        return cls.model_validate(data)
