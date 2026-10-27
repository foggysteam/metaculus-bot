"""
Post-processing of the final aggregated forecast, fitted on the backtest.

Backtest v1 (78 resolved Polymarket/Manifold questions, backtest/RESULTS.md) found
KCAP2.0 too bold: when it said under 15%, the event happened about 1 time in 4.
Pulling binary forecasts towards 50% in log-odds by a factor of 0.8 improved the
log score on both Polymarket and Manifold questions. The best fit was 0.6 to 0.7;
0.8 is the cautious choice because it was fitted on the same questions.
"""
from __future__ import annotations

import math

BINARY_SHRINK = 0.8
CLIP = (0.01, 0.99)


def shrink_binary(p: float, factor: float = BINARY_SHRINK) -> float:
    """Scale the log-odds of p by factor (below 1 pulls towards 50%), then clip."""
    p = min(max(p, CLIP[0]), CLIP[1])
    shrunk = 1 / (1 + math.exp(-factor * math.log(p / (1 - p))))
    return round(min(max(shrunk, CLIP[0]), CLIP[1]), 4)
