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
# forecasting-tools 0.3.5 lets an option go down to 0.1%. If such an option wins, the
# log score against a crowd at a few percent is around -300, so keep every option at 1%.
MC_FLOOR = 0.01


def shrink_binary(p: float, factor: float = BINARY_SHRINK) -> float:
    """Scale the log-odds of p by factor (below 1 pulls towards 50%), then clip."""
    p = min(max(p, CLIP[0]), CLIP[1])
    shrunk = 1 / (1 + math.exp(-factor * math.log(p / (1 - p))))
    return round(min(max(shrunk, CLIP[0]), CLIP[1]), 4)


def floor_probs(probs: list[float], floor: float = MC_FLOOR) -> list[float] | None:
    """Normalise, then raise every option to at least floor, taking the extra mass proportionally
    from the rest. None if nothing needs to change."""
    total = sum(probs)
    probs = [p / total for p in probs]
    low = [p < floor for p in probs]
    if not any(low) or floor * len(probs) >= 1:
        return None
    spare = 1 - floor * sum(low)
    rest = sum(p for p, is_low in zip(probs, low) if not is_low)
    return [floor if is_low else p * spare / rest for p, is_low in zip(probs, low)]


def floor_options(prediction, floor: float = MC_FLOOR):
    """Raise every option of a PredictedOptionList to at least floor (see floor_probs)."""
    from forecasting_tools import PredictedOption, PredictedOptionList  # kept local so the backtest scorer stays light

    new = floor_probs([o.probability for o in prediction.predicted_options], floor)
    if new is None:
        return prediction
    return PredictedOptionList(
        predicted_options=[
            PredictedOption(option_name=o.option_name, probability=p)
            for o, p in zip(prediction.predicted_options, new)
        ]
    )
