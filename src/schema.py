from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Optional[Literal["REFUND", "EXCHANGE", "STORE_CREDIT", "ESCALATE"]] = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_en: str
    reasoning_ar: str
    suggested_reply_en: str
    suggested_reply_ar: str
    is_uncertain: bool
    uncertainty_reason: Optional[str] = None
