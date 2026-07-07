from svs_common.model_registry import select_mode

def test_pdf_markdown_external_detection():
    assert select_mode("book.md", "text/markdown", "auto_detect_v1", {"source_pdf_id": "pdf1"}) == "pdf_markdown_external_v1"

def test_code_detection():
    assert select_mode("main.py", "text/plain", "auto_detect_v1", {}) == "code_repo_v1"
