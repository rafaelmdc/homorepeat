from __future__ import annotations

from enum import StrEnum
from typing import Callable, TypeVar

from .filters import StatsFilterState


class StatsPayloadClassification(StrEnum):
    SYNC = "sync"
    SYNC_CACHE = "sync+cache"
    ASYNC_PERSISTED = "async+persisted"


class StatsPayloadType(StrEnum):
    REPEAT_LENGTH_SUMMARY = "repeat_length.summary"
    REPEAT_LENGTH_OVERVIEW_TYPICAL = "repeat_length.overview_typical"
    REPEAT_LENGTH_OVERVIEW_TAIL = "repeat_length.overview_tail"
    REPEAT_LENGTH_INSPECT = "repeat_length.inspect"
    CODON_COMPOSITION_SUMMARY = "codon_composition.summary"
    CODON_COMPOSITION_OVERVIEW = "codon_composition.overview"
    CODON_COMPOSITION_CHART = "codon_composition.chart"
    CODON_COMPOSITION_INSPECT = "codon_composition.inspect"
    CODON_USAGE_COUNT = "codon_composition.codon_usage_count"
    CODON_LENGTH_SUMMARY = "codon_length.summary"
    CODON_LENGTH_OVERVIEW_PREFERENCE = "codon_length.overview_preference"
    CODON_LENGTH_OVERVIEW_DOMINANCE = "codon_length.overview_dominance"
    CODON_LENGTH_OVERVIEW_SHIFT = "codon_length.overview_shift"
    CODON_LENGTH_OVERVIEW_SIMILARITY = "codon_length.overview_similarity"
    CODON_LENGTH_BROWSE = "codon_length.browse"
    CODON_LENGTH_INSPECT = "codon_length.inspect"
    CODON_LENGTH_COMPARISON = "codon_length.comparison"
    TAXONOMY_GUTTER = "shared.taxonomy_gutter"


_T = TypeVar("_T")


def classify_stats_payload(
    filter_state: StatsFilterState,
    payload_type: StatsPayloadType,
) -> StatsPayloadClassification:
    del filter_state
    del payload_type
    return StatsPayloadClassification.SYNC_CACHE


def build_stats_payload(
    filter_state: StatsFilterState,
    payload_type: StatsPayloadType,
    build_fn: Callable[[], _T],
) -> _T:
    classification = classify_stats_payload(filter_state, payload_type)
    if classification == StatsPayloadClassification.ASYNC_PERSISTED:
        raise NotImplementedError(
            f"Stats payload {payload_type.value!r} is classified as async+persisted and cannot be built inline yet."
        )
    return build_fn()
