"""
core/decision.py — CEREBRO Decision Engine (Survivor + Smart Select)

Responsibilities:
- Choose exactly one survivor per duplicate group (unless overridden)
- Produce an explainable DeletePlan
- Deterministic in validation mode
- Never delete directly (planning only)

Non-negotiable rules:
- Survivors are explicit, not inferred from UI state
- Every delete candidate has a reason
- Decision logic is auditable and replayable
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from cerebro.core.pipeline import (
    CancelToken,
    DeletePlan,
    DeletePlanItem,
    DeletionPolicy,
    PipelineRequest,
)


# ---------------------------------------------------------------------
# 00. SCORING HEURISTICS (EXTENSIBLE)
# ---------------------------------------------------------------------

def _score_item(item) -> int:
    """
    Higher score = more likely to survive.

    Default heuristic (simple but sane):
    - Prefer larger files (often higher quality)
    - Prefer files with richer metadata (if present later)
    """
    score = 0

    # Size-based preference
    try:
        score += int(item.size_bytes // 1024)  # KB-weighted
    except Exception:
        pass

    # Future hooks:
    # - EXIF completeness
    # - Resolution
    # - Creation date proximity
    # - User preferences

    return score


# ---------------------------------------------------------------------
# 01. DECISION ENGINE
# ---------------------------------------------------------------------

class DecisionEngine:
    """
    Concrete implementation of DecisionPort.
    """

    def decide(
        self,
        groups: List[Any],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> Tuple[List[Any], DeletePlan]:
        """
        Returns:
          (updated_groups, delete_plan)

        updated_groups:
          groups annotated only by ordering; no mutation required here

        delete_plan:
          authoritative list of survivors + delete candidates
        """

        token = self._make_token()
        plan_items: List[DeletePlanItem] = []

        for group in groups:
            if cancel.is_cancelled():
                break

            if len(group.items) < 2:
                continue

            survivor, ranked = self._choose_survivor(group, request)

            for item in ranked:
                is_survivor = item is survivor
                reason = (
                    "survivor:selected_by_score"
                    if is_survivor
                    else "duplicate:lower_score"
                )

                plan_items.append(
                    DeletePlanItem(
                        path=item.path,
                        reason=reason,
                        group_id=group.group_id,
                        survivor=is_survivor,
                        size_bytes=item.size_bytes,
                    )
                )

        plan = DeletePlan(
            token=token,
            policy=DeletionPolicy.DRY_RUN,
            items=plan_items,
        )

        return groups, plan

    # -----------------------------------------------------------------
    # 02. SURVIVOR SELECTION
    # -----------------------------------------------------------------

    def _choose_survivor(self, group, request: PipelineRequest):
        """
        Selects exactly one survivor from a group.
        """

        scored: List[Tuple[int, Any]] = []

        for item in group.items:
            score = _score_item(item)
            scored.append((score, item))

        # Deterministic ordering
        if request.validation_mode:
            scored.sort(
                key=lambda t: (
                    -t[0],           # highest score first
                    str(t[1].path),  # stable tie-break
                )
            )
        else:
            scored.sort(key=lambda t: -t[0])

        survivor = scored[0][1]
        ranked_items = [it for _, it in scored]

        return survivor, ranked_items

    # -----------------------------------------------------------------
    # 03. TOKEN GENERATION
    # -----------------------------------------------------------------

    def _make_token(self) -> str:
        """
        Token required for delete confirmation.
        """
        return uuid.uuid4().hex
