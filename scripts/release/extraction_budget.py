#!/usr/bin/env python3
"""Page estimation and an enforced spend budget for the remote extraction path.

One estimator, shared. The extraction plan sizes the workload with it and the
extractor enforces the cap with it, so a cap cannot be computed against one
number and enforced against another.

The budget is deliberately pessimistic at the boundary: a document is admitted
only if its estimate fits entirely within what remains. Pages are estimates, not
measurements, so the run also records what it admitted and refused, and the
actual billed pages must be reconciled against the estimate before the cap for a
larger stage is trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PAGE = re.compile(rb"/Type\s*/Page[^s]")
_COUNT = re.compile(rb"/Type\s*/Pages\b[^>]{0,200}?/Count\s+(\d+)")
_COUNT_FIRST = re.compile(rb"/Count\s+(\d+)[^>]{0,200}?/Type\s*/Pages\b")

# Used only when neither structural reading works, i.e. a fully compressed PDF.
BYTES_PER_PAGE_HEURISTIC = 45_000


def pdf_page_estimate(payload: bytes) -> tuple[int, str]:
    """Approximate page count from raw PDF bytes, with how it was derived.

    Two independent readings, because each fails differently: the page tree's
    ``/Count`` is authoritative when present but hides inside object streams,
    while counting ``/Type /Page`` objects works on uncompressed files and
    undercounts compressed ones. The larger wins, and the basis travels with the
    number so nobody reads an estimate as a measurement.
    """
    counts = [int(match) for match in _COUNT.findall(payload)]
    counts += [int(match) for match in _COUNT_FIRST.findall(payload)]
    by_count = max(counts) if counts else 0
    by_objects = len(_PAGE.findall(payload))
    if by_count >= max(by_objects, 1):
        return max(by_count, 1), "page_tree_count"
    if by_objects:
        return by_objects, "page_object_scan"
    return max(1, round(len(payload) / BYTES_PER_PAGE_HEURISTIC)), "byte_size_heuristic"


def estimate_for(path: Path) -> tuple[int, str]:
    if path.suffix.lower() != ".pdf":
        return 0, "not_billable"
    return pdf_page_estimate(path.read_bytes())


@dataclass
class Budget:
    """An enforced cap on what one extraction stage may spend.

    ``max_pages`` is the billing unit. ``max_documents`` is a second, coarser
    bound so a badly wrong page estimate cannot run away. Either at zero means
    that dimension is uncapped; a budget with both uncapped is explicitly
    ``unlimited()`` so an accidental no-cap is visible in the receipt.
    """

    max_pages: int = 0
    max_documents: int = 0
    admitted_pages: int = 0
    admitted: list[dict[str, Any]] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def unlimited(cls) -> "Budget":
        return cls()

    @property
    def enforced(self) -> bool:
        return bool(self.max_pages or self.max_documents)

    @property
    def pages_remaining(self) -> int | None:
        return None if not self.max_pages else max(self.max_pages - self.admitted_pages, 0)

    def admit(self, document_id: str, pages: int, *, basis: str = "") -> bool:
        """Admit one document if it fits entirely within what remains."""
        if self.max_documents and len(self.admitted) >= self.max_documents:
            self.refused.append({
                "document": document_id, "page_estimate": pages, "basis": basis,
                "reason": f"document cap reached ({self.max_documents})",
            })
            return False
        if self.max_pages and self.admitted_pages + pages > self.max_pages:
            self.refused.append({
                "document": document_id, "page_estimate": pages, "basis": basis,
                "reason": (
                    f"page cap would be exceeded: {self.admitted_pages} admitted + {pages} "
                    f"> {self.max_pages}"
                ),
            })
            return False
        self.admitted.append({"document": document_id, "page_estimate": pages, "basis": basis})
        self.admitted_pages += pages
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "enforced": self.enforced,
            "max_pages": self.max_pages or None,
            "max_documents": self.max_documents or None,
            "admitted_document_count": len(self.admitted),
            "admitted_page_estimate": self.admitted_pages,
            "pages_remaining": self.pages_remaining,
            "refused_count": len(self.refused),
            "refused": self.refused[:50],
            "note": (
                "page counts are estimates; reconcile against the provider's actual billed pages "
                "before trusting this cap for a larger stage"
            ),
        }
