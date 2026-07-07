from svs_common.chunking import code_symbol_chunks, choose_chunker


def test_code_symbol_chunks_detect_python_symbols():
    chunks = code_symbol_chunks('import os\n\ndef alpha():\n    return 1\n\nclass Beta:\n    pass\n')
    headings = [c.heading_path[0] for c in chunks]
    assert 'alpha' in headings
    assert 'Beta' in headings


def test_choose_code_chunker():
    assert choose_chunker('code_repo_v1').__name__ == 'code_symbol_chunks'
