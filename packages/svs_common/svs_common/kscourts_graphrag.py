from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
import itertools
import json
import re
from typing import Any


CASE_CITATION_RE = re.compile(
    r"\b(?P<case_name>(?:In re|State v\.|(?!See\s)(?!Cf\.\s)[A-Z][A-Za-z0-9'&.\- ]+\s+v\.)[^,\n]{2,120}?)"
    r",\s+(?P<volume>\d{1,3})\s+"
    r"(?P<reporter>Kan(?:\. App\. 2d|\. App\.|\.))\s+"
    r"(?P<page>\d{1,4})"
    r"(?:,\s*(?P<pinpoint>\d{1,4}))?"
    r"(?:,\s*(?P<pacific>\d{1,4}\s+P\.(?:2d|3d|4th)\s+\d{1,4}))?"
    r"\s+\((?P<year>\d{4})\)",
)
STATUTE_RE = re.compile(
    r"\bK\.S\.A\.\s+(?:(?P<year>\d{4})\s+Supp\.\s+)?"
    r"(?P<section>\d{1,3}\s*-\s*\d{1,5}[a-z]?(?:\([a-zA-Z0-9]+\))*)",
    re.I,
)
RULE_RE = re.compile(r"\b(?P<label>(?:Supreme Court\s+)?Rule\s+(?P<rule>\d+(?:\.\d+)?[A-Z]?))\b", re.I)
DOCKET_RE = re.compile(r"\bNo\.\s*(?P<docket>\d{1,3},?\d{3}|\d{4,6})\b", re.I)


@dataclass(frozen=True)
class KSCourtsChunkRecord:
    vector_store_id: str
    document_id: str
    chunk_id: str
    chunk_ordinal: int
    text: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedSignal:
    kind: str
    key: str
    label: str
    start: int
    end: int
    attributes: dict[str, Any] = field(default_factory=dict)
    method: str = "regex"
    confidence: float = 0.95


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    payload = "\x1f".join(str(part) for part in parts if part is not None)
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()[:length]}"


def normalize_docket(value: str) -> str:
    return re.sub(r"\D+", "", value)


def normalize_statute_section(value: str) -> str:
    return re.sub(r"\s*-\s*", "-", normalize_space(value))


def normalize_case_citation_name(value: str) -> str:
    normalized = normalize_space(value)
    cue_matches = list(re.finditer(r"(?:^|[.;:]\s+)(?:see also|see|but see|cf\.|compare)\s+", normalized, flags=re.I))
    if cue_matches:
        normalized = normalize_space(normalized[cue_matches[-1].end():])
    embedded_named_case = re.search(r"\b(?:state\s+v\.|in\s+re\s+)", normalized, flags=re.I)
    if embedded_named_case and embedded_named_case.start() > 0:
        normalized = normalize_space(normalized[embedded_named_case.start():])
    leading_patterns = [
        r"^(?:see also|see|but see|cf\.|compare)\s+",
        r"^(?:the\s+)?court\s+in\s+",
        r"^(?:the\s+)?supreme\s+court\s+in\s+",
        r"^in\s+(?=state\s+v\.|[A-Z][A-Za-z0-9'&.\- ]+\s+v\.)",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in leading_patterns:
            updated = re.sub(pattern, "", normalized, count=1, flags=re.I)
            if updated != normalized:
                normalized = normalize_space(updated)
                changed = True
    return normalized


def split_case_parties(title: str) -> list[str]:
    normalized = normalize_space(title)
    if not normalized:
        return []
    if normalized.lower().startswith("in re "):
        return [normalized[6:].strip()]
    if " v. " not in normalized:
        return []
    return [part.strip() for part in normalized.split(" v. ", 1) if part.strip()]


def extraction_provenance(record: KSCourtsChunkRecord, signal: ExtractedSignal | None = None) -> dict[str, Any]:
    attrs = record.attributes
    provenance = {
        "vector_store_id": record.vector_store_id,
        "document_id": record.document_id,
        "chunk_id": record.chunk_id,
        "chunk_ordinal": record.chunk_ordinal,
        "title": attrs.get("title"),
        "docket_number": attrs.get("docket_number"),
        "decision_date": attrs.get("decision_date"),
        "court": attrs.get("court"),
        "status": attrs.get("status"),
        "source_pdf_filename": attrs.get("source_pdf_filename"),
        "source_pdf_path": attrs.get("source_pdf_path"),
        "sha256": attrs.get("sha256"),
    }
    if signal:
        provenance.update({
            "span_start": signal.start,
            "span_end": signal.end,
            "evidence": record.text[signal.start:signal.end],
            "extraction_method": signal.method,
            "confidence": signal.confidence,
        })
    return {key: value for key, value in provenance.items() if value is not None}


def extract_signals(text: str) -> list[ExtractedSignal]:
    signals: list[ExtractedSignal] = []
    for match in CASE_CITATION_RE.finditer(text):
        raw_case_name = match.group("case_name")
        case_name = normalize_case_citation_name(raw_case_name)
        case_name_offset = raw_case_name.lower().rfind(case_name.lower())
        start = match.start("case_name") + case_name_offset if case_name_offset >= 0 else match.start()
        volume = match.group("volume")
        reporter = normalize_space(match.group("reporter"))
        page = match.group("page")
        year = match.group("year")
        citation = f"{case_name}, {volume} {reporter} {page} ({year})"
        signals.append(ExtractedSignal(
            kind="case_citation",
            key=normalize_key(citation),
            label=citation,
            start=start,
            end=match.end(),
            attributes={
                "case_name": case_name,
                "volume": volume,
                "reporter": reporter,
                "page": page,
                "pinpoint": match.group("pinpoint"),
                "parallel_citation": match.group("pacific"),
                "year": year,
            },
        ))
    for match in STATUTE_RE.finditer(text):
        section = normalize_statute_section(match.group("section"))
        year = match.group("year")
        label = f"K.S.A. {year} Supp. {section}" if year else f"K.S.A. {section}"
        signals.append(ExtractedSignal(
            kind="statute",
            key=normalize_key(label),
            label=label,
            start=match.start(),
            end=match.end(),
            attributes={"section": section, "year": year},
        ))
    for match in RULE_RE.finditer(text):
        rule = match.group("rule")
        label = normalize_space(match.group("label"))
        signals.append(ExtractedSignal(
            kind="rule",
            key=normalize_key(label),
            label=label,
            start=match.start(),
            end=match.end(),
            attributes={"rule": rule},
        ))
    for match in DOCKET_RE.finditer(text):
        docket = normalize_docket(match.group("docket"))
        signals.append(ExtractedSignal(
            kind="docket_reference",
            key=docket,
            label=docket,
            start=match.start(),
            end=match.end(),
            attributes={"docket_number": docket},
        ))
    signals.sort(key=lambda signal: (signal.start, signal.end, signal.kind, signal.key))
    return signals


def _node(node_type: str, key: str, label: str, attributes: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": stable_id(f"node_{node_type}", key),
        "type": node_type,
        "key": key,
        "label": label,
        "attributes": {key: value for key, value in attributes.items() if value is not None},
        "provenance": [provenance],
    }


def _edge(edge_type: str, source: str, target: str, attributes: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    edge_attributes_key = json.dumps(attributes, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "id": stable_id(
            "edge",
            edge_type,
            source,
            target,
            edge_attributes_key,
            provenance.get("chunk_id"),
            provenance.get("span_start"),
            provenance.get("span_end"),
        ),
        "type": edge_type,
        "source": source,
        "target": target,
        "attributes": {key: value for key, value in attributes.items() if value is not None},
        "provenance": provenance,
    }


def _merge_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    existing = nodes.get(node["id"])
    if not existing:
        nodes[node["id"]] = node
        return
    existing["attributes"].update({key: value for key, value in node["attributes"].items() if key not in existing["attributes"]})
    provenance_keys = {
        (item.get("document_id"), item.get("chunk_id"), item.get("span_start"), item.get("span_end"))
        for item in existing["provenance"]
    }
    for item in node["provenance"]:
        key = (item.get("document_id"), item.get("chunk_id"), item.get("span_start"), item.get("span_end"))
        if key not in provenance_keys:
            existing["provenance"].append(item)


def build_graph(records: list[KSCourtsChunkRecord]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    node_occurrences = 0
    extraction_errors = 0

    opinion_nodes_by_document: dict[str, str] = {}
    opinion_attrs_by_document: dict[str, dict[str, Any]] = {}
    docket_to_opinions: defaultdict[str, set[str]] = defaultdict(set)
    party_to_opinions: defaultdict[str, set[str]] = defaultdict(set)
    court_to_opinions: defaultdict[str, set[str]] = defaultdict(set)
    year_to_opinions: defaultdict[str, set[str]] = defaultdict(set)

    first_record_by_document: dict[str, KSCourtsChunkRecord] = {}
    for record in records:
        first_record_by_document.setdefault(record.document_id, record)

    for document_id, record in first_record_by_document.items():
        attrs = record.attributes
        title = normalize_space(str(attrs.get("title") or document_id))
        docket = normalize_docket(str(attrs.get("docket_number") or ""))
        decision_date = str(attrs.get("decision_date") or "")
        year = str(attrs.get("decision_year") or decision_date[:4] or "")
        court = normalize_space(str(attrs.get("court") or ""))
        status = normalize_space(str(attrs.get("status") or ""))
        base_provenance = extraction_provenance(record)

        opinion = _node("opinion", document_id, title, {
            "document_id": document_id,
            "title": title,
            "docket_number": docket or None,
            "decision_date": decision_date or None,
            "decision_year": year or None,
            "court": court or None,
            "status": status or None,
        }, base_provenance)
        node_occurrences += 1
        _merge_node(nodes, opinion)
        opinion_id = opinion["id"]
        opinion_nodes_by_document[document_id] = opinion_id
        opinion_attrs_by_document[document_id] = opinion["attributes"]

        case = _node("case", normalize_key(title), title, {"title": title}, base_provenance)
        node_occurrences += 1
        _merge_node(nodes, case)
        edges.append(_edge("source_document", opinion_id, case["id"], {}, base_provenance))

        if docket:
            docket_node = _node("docket", docket, docket, {"docket_number": docket}, base_provenance)
            node_occurrences += 1
            _merge_node(nodes, docket_node)
            docket_to_opinions[docket].add(opinion_id)
            edges.append(_edge("has_docket", opinion_id, docket_node["id"], {}, base_provenance))
        if court:
            court_node = _node("court", normalize_key(court), court, {"court": court}, base_provenance)
            node_occurrences += 1
            _merge_node(nodes, court_node)
            court_to_opinions[court].add(opinion_id)
            edges.append(_edge("same_court", opinion_id, court_node["id"], {}, base_provenance))
        if year:
            year_node = _node("year", year, year, {"year": year}, base_provenance)
            node_occurrences += 1
            _merge_node(nodes, year_node)
            year_to_opinions[year].add(opinion_id)
            edges.append(_edge("same_year", opinion_id, year_node["id"], {}, base_provenance))
        if status:
            status_node = _node("publication_status", normalize_key(status), status, {"status": status}, base_provenance)
            node_occurrences += 1
            _merge_node(nodes, status_node)
            edges.append(_edge("published_status", opinion_id, status_node["id"], {}, base_provenance))
        for party in split_case_parties(title):
            party_node = _node("party", normalize_key(party), party, {"name": party}, base_provenance)
            node_occurrences += 1
            _merge_node(nodes, party_node)
            party_to_opinions[normalize_key(party)].add(opinion_id)
            edges.append(_edge("same_party", opinion_id, party_node["id"], {"party": party}, base_provenance))

    for record in records:
        opinion_id = opinion_nodes_by_document.get(record.document_id)
        if not opinion_id:
            continue
        try:
            signals = extract_signals(record.text)
        except Exception:
            extraction_errors += 1
            continue
        for signal in signals:
            provenance = extraction_provenance(record, signal)
            if signal.kind == "case_citation":
                case_name = signal.attributes["case_name"]
                case_node = _node("case", normalize_key(case_name), case_name, {"title": case_name}, provenance)
                citation_node = _node("citation", signal.key, signal.label, signal.attributes, provenance)
                node_occurrences += 2
                _merge_node(nodes, case_node)
                _merge_node(nodes, citation_node)
                edges.append(_edge("cites_case", opinion_id, case_node["id"], signal.attributes, provenance))
                edges.append(_edge("has_citation", case_node["id"], citation_node["id"], signal.attributes, provenance))
            elif signal.kind == "statute":
                statute_node = _node("statute", signal.key, signal.label, signal.attributes, provenance)
                node_occurrences += 1
                _merge_node(nodes, statute_node)
                edges.append(_edge("cites_statute", opinion_id, statute_node["id"], signal.attributes, provenance))
            elif signal.kind == "rule":
                rule_node = _node("rule", signal.key, signal.label, signal.attributes, provenance)
                node_occurrences += 1
                _merge_node(nodes, rule_node)
                edges.append(_edge("cites_rule", opinion_id, rule_node["id"], signal.attributes, provenance))
            elif signal.kind == "docket_reference":
                docket_node = _node("docket", signal.key, signal.label, signal.attributes, provenance)
                node_occurrences += 1
                _merge_node(nodes, docket_node)
                edges.append(_edge("mentions_docket", opinion_id, docket_node["id"], signal.attributes, provenance))

    for docket, opinion_ids in docket_to_opinions.items():
        for left, right in itertools.combinations(sorted(opinion_ids), 2):
            provenance = {"docket_number": docket, "extraction_method": "metadata", "confidence": 1.0}
            edges.append(_edge("same_docket", left, right, {"docket_number": docket}, provenance))
    for party_key, opinion_ids in party_to_opinions.items():
        for left, right in itertools.combinations(sorted(opinion_ids)[:50], 2):
            provenance = {"party_key": party_key, "extraction_method": "metadata", "confidence": 1.0}
            edges.append(_edge("related_party", left, right, {"party_key": party_key}, provenance))

    node_list = sorted(nodes.values(), key=lambda item: item["id"])
    edge_map = {edge["id"]: edge for edge in edges}
    edge_list = sorted(edge_map.values(), key=lambda item: item["id"])
    node_counts = Counter(node["type"] for node in node_list)
    edge_counts = Counter(edge["type"] for edge in edge_list)
    summary = {
        "schema_version": 1,
        "records_processed": len(records),
        "documents_processed": len(first_record_by_document),
        "nodes": len(node_list),
        "edges": len(edge_list),
        "node_counts": dict(sorted(node_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "duplicate_merged_node_count": max(0, node_occurrences - len(node_list)),
        "duplicate_merged_edge_count": max(0, len(edges) - len(edge_list)),
        "unresolved_citation_count": 0,
        "extraction_error_count": extraction_errors,
        "backend_recommendation": "postgres_first",
        "backend_recommendation_reason": (
            "Use JSONL/Postgres staging first because the graph is tenant-local, provenance-heavy, "
            "and should be evaluated before adding a graph database service."
        ),
    }
    return {"nodes": node_list, "edges": edge_list, "summary": summary}
