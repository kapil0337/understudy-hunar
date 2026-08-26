"""Output shape for deterministic candidate/job matching (app/services/ranking.py).

Mirrors app/schemas/rehearsal.py's rule for RehearsalScore: the composite number is never handed
back without the breakdown it was computed from, so the UI can render a segmented bar per
CONTRIBUTING.md rather than showing an opaque score.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MatchComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float  # 0-100
    weight: float  # 0-100, all components sum to 100


class MatchBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_score: float  # 0-100, the weighted composite
    components: dict[str, MatchComponent]
