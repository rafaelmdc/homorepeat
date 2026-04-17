from __future__ import annotations

from dataclasses import dataclass


LENGTH_BIN_SIZE = 5


@dataclass(frozen=True)
class LengthBinDefinition:
    start: int
    end: int
    key: str
    label: str
    index: int


def build_length_bin_definition(length: int) -> LengthBinDefinition:
    normalized_length = max(int(length), 0)
    start = (normalized_length // LENGTH_BIN_SIZE) * LENGTH_BIN_SIZE
    return build_length_bin_definition_for_start(start)


def build_length_bin_definition_for_start(start: int) -> LengthBinDefinition:
    normalized_start = max(int(start), 0)
    aligned_start = (normalized_start // LENGTH_BIN_SIZE) * LENGTH_BIN_SIZE
    end = aligned_start + LENGTH_BIN_SIZE - 1
    label = f"{aligned_start}-{end}"
    return LengthBinDefinition(
        start=aligned_start,
        end=end,
        key=label,
        label=label,
        index=aligned_start // LENGTH_BIN_SIZE,
    )


def build_visible_length_bins(bin_starts) -> list[LengthBinDefinition]:
    normalized_starts = sorted(
        {
            build_length_bin_definition_for_start(bin_start).start
            for bin_start in bin_starts
        }
    )
    if not normalized_starts:
        return []

    return [
        build_length_bin_definition_for_start(bin_start)
        for bin_start in range(
            normalized_starts[0],
            normalized_starts[-1] + LENGTH_BIN_SIZE,
            LENGTH_BIN_SIZE,
        )
    ]
