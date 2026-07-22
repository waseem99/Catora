from __future__ import annotations


class EnrichmentGatewayError(RuntimeError):
    pass


class BudgetExceededError(EnrichmentGatewayError):
    pass


class ProviderContractError(EnrichmentGatewayError):
    pass


class InvalidProviderOutputError(EnrichmentGatewayError):
    pass
