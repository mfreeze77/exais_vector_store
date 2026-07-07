from svs_common.chunking import markdown_heading_chunks, pdf_markdown_external_chunks

def test_markdown_heading_chunks_preserve_heading():
    chunks = markdown_heading_chunks("# A\nhello world\n## B\nmore text")
    assert chunks[0].heading_path == ["A"]
    assert chunks[-1].heading_path == ["A", "B"]

def test_pdf_markdown_external_page_marker():
    chunks = pdf_markdown_external_chunks("<!-- page: 12 -->\n# Section\nText")
    assert chunks[0].page_start == 12

def test_pdf_markdown_external_inline_page_marker():
    chunks = pdf_markdown_external_chunks("Page 1 Hello Marker Upload Search Proof")
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1
