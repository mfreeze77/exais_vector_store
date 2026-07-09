from types import SimpleNamespace

from svs_common.openai_compat import file_attribute_payload_key
from svs_common.opensearch_adapter import OpenSearchAdapter


class _Indices:
    def __init__(self):
        self.created_body = None

    def exists(self, index):
        return False

    def create(self, index, body):
        self.created_body = body


class _Client:
    def __init__(self):
        self.indices = _Indices()
        self.search_body = None

    def search(self, index, body):
        self.search_body = body
        return {"hits": {"hits": []}}


def test_opensearch_file_attribute_payload_fields_are_keyword_mapped():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.client = _Client()
    adapter.settings = SimpleNamespace(svs_index_strict=True)

    adapter.ensure_index("idx")

    assert adapter.client.indices.created_body["mappings"]["dynamic_templates"] == [
        {"file_attributes": {"match": "file_attr_*", "mapping": {"type": "keyword"}}}
    ]


def test_opensearch_search_supports_file_attribute_alternatives():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.client = _Client()
    adapter.settings = SimpleNamespace(svs_index_strict=True)

    results = adapter.search(
        "idx",
        "deep research",
        {
            "tenant_id": "tenant",
            "business_instance_id": "biz",
            "max_security_level": 5,
            "file_attribute_filters": {"region": "us"},
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
                {"key": "priority", "op": "lt", "value": 10},
            ],
        },
        10,
    )

    filter_clauses = adapter.client.search_body["query"]["bool"]["filter"]
    region_key = file_attribute_payload_key("region")
    category_key = file_attribute_payload_key("category")

    assert results == []
    assert {"term": {region_key: "us"}} in filter_clauses
    assert {"range": {file_attribute_payload_key("created_at"): {"gte": "2026-01-01"}}} in filter_clauses
    assert {"range": {file_attribute_payload_key("priority"): {"lt": 10}}} in filter_clauses
    assert {
        "bool": {
            "should": [
                {"bool": {"filter": [{"term": {category_key: "blog"}}]}},
                {"bool": {"filter": [{"term": {category_key: "announcement"}}]}},
            ],
            "minimum_should_match": 1,
        }
    } in filter_clauses


def test_opensearch_search_uses_phrase_aware_text_query():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.client = _Client()
    adapter.settings = SimpleNamespace(svs_index_strict=True)

    adapter.search(
        "idx",
        '"marker warmup" retries',
        {
            "tenant_id": "tenant",
            "business_instance_id": "biz",
            "max_security_level": 5,
        },
        10,
    )

    text_query = adapter.client.search_body["query"]["bool"]["must"][0]
    assert text_query == {
        "bool": {
            "should": [
                {"match_phrase": {"text": {"query": '"marker warmup" retries', "boost": 3.0}}},
                {"match": {"text": {"query": '"marker warmup" retries', "operator": "and", "boost": 1.5}}},
                {"match": {"text": {"query": '"marker warmup" retries'}}},
            ],
            "minimum_should_match": 1,
        }
    }


def test_opensearch_search_supports_file_attribute_negation():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.client = _Client()
    adapter.settings = SimpleNamespace(svs_index_strict=True)

    results = adapter.search(
        "idx",
        "deep research",
        {
            "tenant_id": "tenant",
            "business_instance_id": "biz",
            "max_security_level": 5,
            "file_attribute_not_filters": [{"key": "region", "value": "us"}],
            "file_attribute_not_any": [{"key": "category", "values": ["blog", "announcement"]}],
        },
        10,
    )

    filter_clauses = adapter.client.search_body["query"]["bool"]["filter"]
    must_not = adapter.client.search_body["query"]["bool"]["must_not"]
    region_key = file_attribute_payload_key("region")
    category_key = file_attribute_payload_key("category")

    assert results == []
    assert {"exists": {"field": region_key}} in filter_clauses
    assert {"exists": {"field": category_key}} in filter_clauses
    assert {"term": {region_key: "us"}} in must_not
    assert {"terms": {category_key: ["blog", "announcement"]}} in must_not
