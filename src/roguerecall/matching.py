from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar


Value = TypeVar("Value")


@dataclass(frozen=True)
class ContiguousRun:
    response_start: int
    reference_start: int
    length: int


def longest_common_contiguous_run(
    response: list[Value], reference: list[Value]
) -> ContiguousRun:
    """Return the earliest longest contiguous run shared by two sequences."""

    best = ContiguousRun(0, 0, 0)
    previous = [0] * (len(reference) + 1)
    for response_index, response_value in enumerate(response):
        current = [0] * (len(reference) + 1)
        for reference_index, reference_value in enumerate(reference):
            if response_value == reference_value:
                length = previous[reference_index] + 1
                current[reference_index + 1] = length
                if length > best.length:
                    best = ContiguousRun(
                        response_index - length + 1,
                        reference_index - length + 1,
                        length,
                    )
        previous = current
    return best
