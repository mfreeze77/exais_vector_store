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

    Three dimensions, because each fails differently:

    * ``max_pages`` -- the provider's billing unit.
    * ``max_documents`` -- a coarser bound, so a badly wrong page estimate
      cannot run away.
    * ``max_spend`` with ``unit_price_per_page`` -- an actual money limit.
      Pages are a proxy for cost; only this one is denominated in currency.

    Every dimension is charged at the WORST CASE, not the happy path: a document
    may be attempted ``attempts`` times and the provider bills each attempt, so
    admitting one document reserves ``pages * attempts``. A cap that assumes one
    attempt is not a cap on what the invoice can say.

    Either count at zero means that dimension is uncapped; a budget with nothing
    set is explicitly ``unlimited()`` so an accidental no-cap is visible.
    """

    max_pages: int = 0
    max_documents: int = 0
    max_spend: float = 0.0
    unit_price_per_page: float = 0.0
    attempts: int = 1
    admitted_pages: int = 0
    admitted: list[dict[str, Any]] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def unlimited(cls) -> "Budget":
        return cls()

    @property
    def enforced(self) -> bool:
        return bool(self.max_pages or self.max_documents or self.max_spend)

    @property
    def worst_case_attempts(self) -> int:
        return max(1, self.attempts)

    @property
    def pages_remaining(self) -> int | None:
        return None if not self.max_pages else max(self.max_pages - self.admitted_pages, 0)

    @property
    def admitted_spend(self) -> float | None:
        if not self.unit_price_per_page:
            return None
        return round(self.admitted_pages * self.unit_price_per_page, 4)

    def _refuse(self, document_id: str, pages: int, basis: str, reason: str) -> bool:
        self.refused.append({
            "document": document_id, "page_estimate": pages,
            "worst_case_pages": pages * self.worst_case_attempts,
            "basis": basis, "reason": reason,
        })
        return False

    def admit(self, document_id: str, pages: int, *, basis: str = "") -> bool:
        """Admit one document if its worst case fits entirely within what remains."""
        charge = pages * self.worst_case_attempts
        if self.max_documents and len(self.admitted) >= self.max_documents:
            return self._refuse(document_id, pages, basis,
                                f"document cap reached ({self.max_documents})")
        if self.max_pages and self.admitted_pages + charge > self.max_pages:
            return self._refuse(
                document_id, pages, basis,
                f"page cap would be exceeded: {self.admitted_pages} reserved + {charge} "
                f"(= {pages} pages x {self.worst_case_attempts} attempts) > {self.max_pages}",
            )
        if self.max_spend:
            if not self.unit_price_per_page:
                return self._refuse(document_id, pages, basis,
                                    "a spend cap needs unit_price_per_page to be meaningful")
            projected = round((self.admitted_pages + charge) * self.unit_price_per_page, 4)
            if projected > self.max_spend:
                return self._refuse(
                    document_id, pages, basis,
                    f"spend cap would be exceeded: {projected} > {self.max_spend}",
                )
        self.admitted.append({
            "document": document_id, "page_estimate": pages,
            "worst_case_pages": charge, "basis": basis,
        })
        self.admitted_pages += charge
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "enforced": self.enforced,
            "max_pages": self.max_pages or None,
            "max_documents": self.max_documents or None,
            "max_spend": self.max_spend or None,
            "unit_price_per_page": self.unit_price_per_page or None,
            "attempts_charged_per_document": self.worst_case_attempts,
            "admitted_document_count": len(self.admitted),
            "reserved_page_estimate": self.admitted_pages,
            "reserved_spend_estimate": self.admitted_spend,
            "pages_remaining": self.pages_remaining,
            "refused_count": len(self.refused),
            "refused": self.refused[:50],
            "note": (
                "pages are reserved at worst case (estimate x attempts) and page counts are "
                "themselves estimates; reconcile against the provider's actual billed pages before "
                "trusting these caps for a larger stage"
            ),
        }
