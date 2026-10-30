"""Token and cost accounting. Prices are configuration, not code: USD per 1M tokens,
overridable with LOCQA_PRICE_INPUT / LOCQA_PRICE_OUTPUT for a model not listed here."""

from __future__ import annotations

import os
from dataclasses import dataclass

# USD per 1M tokens (input, output), standard tier, prompts under 200k tokens.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
    "fake": (0.0, 0.0),
}


def price_for(model: str) -> tuple[float, float] | None:
    env_in, env_out = os.environ.get("LOCQA_PRICE_INPUT"), os.environ.get("LOCQA_PRICE_OUTPUT")
    if env_in and env_out:
        return float(env_in), float(env_out)
    return PRICES.get(model)


@dataclass
class CostTracker:
    model: str
    budget_usd: float | None = None
    requests: int = 0
    cached_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def price(self) -> tuple[float, float] | None:
        return price_for(self.model)

    @property
    def cost_usd(self) -> float:
        if self.price is None:
            return 0.0
        p_in, p_out = self.price
        return (self.input_tokens * p_in + self.output_tokens * p_out) / 1_000_000

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.requests += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    @property
    def over_budget(self) -> bool:
        return self.budget_usd is not None and self.cost_usd >= self.budget_usd

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "requests": self.requests,
            "cached_requests": self.cached_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "price_usd_per_1m": list(self.price) if self.price else None,
            "cost_usd": round(self.cost_usd, 6),
            "budget_usd": self.budget_usd,
            # On the Google AI Studio free tier nothing is billed; cost_usd is then what the
            # same run would cost on the paid tier.
            "free_tier": self.free_tier,
            "billed_usd": 0.0 if self.free_tier else round(self.cost_usd, 6),
        }

    @property
    def free_tier(self) -> bool:
        return os.environ.get("LOCQA_FREE_TIER", "").strip().lower() in ("1", "true", "yes")
