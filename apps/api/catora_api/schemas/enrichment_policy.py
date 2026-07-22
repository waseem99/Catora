from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from catora_api.enrichment.types import BrandControls


class WorkspaceEnrichmentPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_controls: BrandControls
    max_run_budget_microunits: int | None = Field(default=None, ge=1)


class WorkspaceEnrichmentPolicyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    brand_controls: BrandControls
    max_run_budget_microunits: int | None
    created_at: datetime
    updated_at: datetime
