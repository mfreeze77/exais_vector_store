from svs_common.model_registry import select_mode

def test_pdf_markdown_external_detection():
    assert select_mode("book.md", "text/markdown", "auto_detect_v1", {"source_pdf_id": "pdf1"}) == "pdf_markdown_external_v1"

def test_code_detection():
    assert select_mode("main.py", "text/plain", "auto_detect_v1", {}) == "code_repo_v1"

def test_table_detection_uses_extension_and_mime_type():
    assert select_mode("panel.tsv", "text/plain", "auto_detect_v1", {}) == "tables_csv_json_v1"
    assert select_mode("export.txt", "text/csv", "auto_detect_v1", {}) == "tables_csv_json_v1"

def test_log_detection_uses_extension_and_mime_type():
    assert select_mode("worker.log", "text/plain", "auto_detect_v1", {}) == "logs_errors_v1"
    assert select_mode("worker.txt", "text/x-log", "auto_detect_v1", {}) == "logs_errors_v1"
