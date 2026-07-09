from types import SimpleNamespace

from svs_common.opensearch_adapter import OpenSearchAdapter
from svs_common.qdrant_adapter import QdrantAdapter


def test_qdrant_collection_name_preserves_default_without_index_version():
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix="svs_", svs_index_version="")

    assert adapter.collection_name("biz-dev", "openai-text-embedding-3-small-1536") == (
        "svs_biz_dev_openai_text_embedding_3_small_1536"
    )


def test_qdrant_collection_name_adds_safe_index_version_suffix():
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix="svs_", svs_index_version="Green Canary 01")

    assert adapter.collection_name("Biz Dev", "OpenAI-Profile") == "svs_biz_dev_openai_profile_green_canary_01"


def test_opensearch_index_name_preserves_default_without_index_version():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.settings = SimpleNamespace(opensearch_index_prefix="svs_", svs_index_version="")

    assert adapter.index_name("biz-dev") == "svs_chunks_biz_dev"


def test_opensearch_index_name_adds_safe_index_version_suffix():
    adapter = OpenSearchAdapter.__new__(OpenSearchAdapter)
    adapter.settings = SimpleNamespace(opensearch_index_prefix="svs_", svs_index_version="Blue Cutover")

    assert adapter.index_name("Biz Dev") == "svs_chunks_biz_dev_blue_cutover"
