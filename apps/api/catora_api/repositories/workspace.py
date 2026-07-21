from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceRepository[T]:
    """Repository that cannot construct an unscoped entity query."""

    def __init__(self, session: AsyncSession, model: type[T], workspace_id: uuid.UUID) -> None:
        self._session = session
        self._model = model
        self.workspace_id = workspace_id

    def select_all(self) -> Select[tuple[T]]:
        model = cast(Any, self._model)
        return select(self._model).where(model.workspace_id == self.workspace_id)

    def select_by_id(self, entity_id: uuid.UUID) -> Select[tuple[T]]:
        model = cast(Any, self._model)
        return self.select_all().where(model.id == entity_id)

    async def get(self, entity_id: uuid.UUID) -> T | None:
        result = await self._session.scalar(self.select_by_id(entity_id))
        if result is None:
            return None
        return result

    def assert_workspace(self, entity: T) -> None:
        entity_workspace_id = cast(Any, entity).workspace_id
        if entity_workspace_id != self.workspace_id:
            raise PermissionError("Entity belongs to a different workspace")
