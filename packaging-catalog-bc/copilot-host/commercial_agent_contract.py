from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


AgentType = Literal[
    "lowMargin",
    "costChange",
    "incorrectItem",
]


class CommercialEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidenceType: str = Field(min_length=1, max_length=50)
    sourceSystem: str = Field(min_length=1, max_length=30)
    sourceRecordType: str = Field(min_length=1, max_length=50)
    sourceSystemId: UUID | None = None
    metric: str = Field(min_length=1, max_length=50)
    currentValue: str = Field(max_length=250)
    comparisonValue: str | None = Field(default=None, max_length=250)
    variance: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    weight: float = Field(default=50, ge=0, le=100)
    explanation: str = Field(default="", max_length=1024)
    provenance: str = Field(min_length=1, max_length=250)


class CommercialEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contractVersion: Literal["1.0"] = "1.0"
    agentType: AgentType
    correlationId: UUID
    sourceType: str = Field(min_length=1, max_length=50)
    sourceSystemId: UUID | None = None
    sourceKey: str = Field(min_length=1, max_length=100)
    customerNo: str | None = Field(default=None, max_length=20)
    itemNo: str | None = Field(default=None, max_length=20)
    documentType: str | None = Field(default=None, max_length=30)
    documentNo: str | None = Field(default=None, max_length=20)
    authoritativeFacts: dict[str, Any]
    context: dict[str, Any]
    evidence: list[CommercialEvidence] = Field(default_factory=list, max_length=200)


class CommercialEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contractVersion: Literal["1.0"] = "1.0"
    agentType: AgentType
    correlationId: UUID
    shouldSurface: bool
    severity: int = Field(ge=0, le=100)
    riskScore: float = Field(ge=0, le=100)
    confidenceScore: float = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=250)
    finding: str = Field(min_length=1, max_length=2048)
    recommendedAction: str = Field(max_length=2048)
    evidenceUsed: list[str] = Field(default_factory=list, max_length=100)
    missingContext: list[str] = Field(default_factory=list, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    evaluationVersion: str = Field(min_length=1, max_length=20)

    @field_validator("evidenceUsed", "missingContext")
    @classmethod
    def reject_blank_list_values(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("List values may not be blank.")
        return value
