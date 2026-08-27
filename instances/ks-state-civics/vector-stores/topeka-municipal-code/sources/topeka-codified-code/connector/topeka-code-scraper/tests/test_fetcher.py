from topeka_code_scraper.fetcher import has_municipal_code_content, is_challenge_only_page


def test_challenge_only_page_is_blocked():
    html = "<html><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"

    assert is_challenge_only_page(403, {"cf-mitigated": "challenge"}, html)
    assert is_challenge_only_page(200, {}, html)


def test_rendered_code_page_with_challenge_script_is_allowed():
    html = """
    <html>
      <body>
        <h1>TOPEKA MUNICIPAL CODE</h1>
        <a href="/TMC/18.55.010">18.55.010</a>
        <p>Chapter 18.55 Definitions</p>
        <script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>
      </body>
    </html>
    """

    assert has_municipal_code_content(html)
    assert not is_challenge_only_page(200, {}, html)
