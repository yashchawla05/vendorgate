"""External registry checks behind an interface.

Real GST-portal lookups and bank account verification ("penny drop") need paid or
credentialed providers (GSTN-authorised GSPs; bank-verification APIs from payment
companies). For the demo we implement the interface with a clearly labelled
SimulatedRegistry that reads data/registry/simulated_registry.json.

To plug in a real provider: write a class with the same two methods that calls the
provider's API (with timeout + retries), return the same dict shape, and select it in
get_registry() via an env var. No stage code changes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Protocol

from core.config import REGISTRY_FILE


class RegistryClient(Protocol):
    label: str
    simulated: bool

    def lookup_gstin(self, gstin: str) -> dict | None:
        """{'status': 'Active'|'Cancelled'|..., 'legal_name': str, 'state': str} or None if unknown."""

    def verify_bank_account(self, bank_code: str, account_number: str) -> dict | None:
        """{'holder_name': str, 'bank_name': str} or None if the account is unknown."""


class SimulatedRegistry:
    label = "SIMULATED registry (local JSON, synthetic data only)"
    simulated = True

    def __init__(self, data: dict | None = None):
        self.data = data if data is not None else json.loads(REGISTRY_FILE.read_text())

    def lookup_gstin(self, gstin: str) -> dict | None:
        return self.data.get("gstins", {}).get(gstin.upper())

    def verify_bank_account(self, bank_code: str, account_number: str) -> dict | None:
        return self.data.get("bank_accounts", {}).get(f"{bank_code}:{account_number}")


@lru_cache(maxsize=1)
def get_registry() -> RegistryClient:
    return SimulatedRegistry()
