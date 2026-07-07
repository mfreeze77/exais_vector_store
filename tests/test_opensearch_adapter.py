from types import SimpleNamespace

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


def test_opensearch_file_attribute_payload_fields_are_keyword_mapped():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.client = _Client()
    adapter.settings = SimpleNamespace(svs_index_strict=True)

    adapter.ensure_index("idx")

    assert adapter.client.indices.created_body["mappings"]["dynamic_templates"] == [
        {"file_attributes": {"match": "file_attr_*", "mapping": {"type": "keyword"}}}
    ]
