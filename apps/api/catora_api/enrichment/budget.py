from __future__ import annotations

import asyncio
from dataclasses import dataclass

from catora_api.enrichment.errors import BudgetExceededError, ProviderContractError


@dataclass(frozen=True, slots=True)
class Reservation:
    amount: int


class BudgetLedger:
    def __init__(self, budget_microunits: int) -> None:
        if budget_microunits < 0:
            raise ValueError("budget_microunits cannot be negative")
        self._budget = budget_microunits
        self._spent = 0
        self._reserved = 0
        self._lock = asyncio.Lock()

    @property
    def budget_microunits(self) -> int:
        return self._budget

    @property
    def spent_microunits(self) -> int:
        return self._spent

    async def reserve(self, amount: int) -> Reservation:
        if amount < 0:
            raise ProviderContractError("provider cost estimate cannot be negative")
        async with self._lock:
            if self._spent + self._reserved + amount > self._budget:
                raise BudgetExceededError("enrichment run budget would be exceeded")
            self._reserved += amount
        return Reservation(amount=amount)

    async def settle(self, reservation: Reservation, actual: int) -> None:
        if actual < 0:
            raise ProviderContractError("provider usage cost cannot be negative")
        async with self._lock:
            self._reserved -= reservation.amount
            self._spent += actual
            if actual > reservation.amount:
                raise ProviderContractError(
                    "provider usage exceeded its reserved maximum cost estimate"
                )

    async def release(self, reservation: Reservation) -> None:
        async with self._lock:
            self._reserved -= reservation.amount
