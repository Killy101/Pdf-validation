"""Exercise Scrapling in a real browser with guarded synthetic HTTP responses."""
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings
from app.services.pdf_validation_browser import render_document
from app.services.pdf_validation_collection import collect_document
from app.services.pdf_validation_source import SourceSnapshot, extract_html


URL = "https://publisher.example/rules/viewer"
TEXT = "The operator must retain complete annual records and submit a signed report to the authority within thirty days of each application."


@pytest.fixture
def browser_source(monkeypatch):
    pytest.importorskip("scrapling.fetchers")
    if sys.platform == "win32" and not Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe").exists():
        pytest.skip("Installed Edge is unavailable")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs:
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8" if host == "publisher.example" else "127.0.0.1", 443))])
    monkeypatch.setattr(settings, "PDF_VALIDATION_BROWSER_RULES", {})
    pages, calls = {}, []
    def fetch(url, hosts, max_bytes, timeout):
        calls.append(url)
        return SourceSnapshot(pages[url].encode(), url, "html", "text/html")
    def run(markup, **rules):
        pages[URL] = '<html lang="en"><body>' + markup + '</body></html>'
        monkeypatch.setattr(settings, "PDF_VALIDATION_BROWSER_RULES", {"publisher.example": rules})
        return render_document(fetch(URL, (), 0, 0), ("publisher.example",), fetch, 15)
    return run, pages, calls, fetch


def test_dynamic_tabs_and_closed_details_are_collected(browser_source):
    run, _, calls, _ = browser_source
    snapshot, complete, notes = run(f'''<main><h1>Synthetic Regulation</h1>
      <div role="tablist"><button role="tab" aria-controls="first">First</button>
      <button role="tab" aria-controls="second" onclick="document.getElementById('second').hidden=false">Second</button></div>
      <section id="first" role="tabpanel"><h2>Section 1 Scope</h2><p>{TEXT}</p></section>
      <section id="second" role="tabpanel" hidden><h2>Section 2 Records</h2><p>Second chapter wording.</p></section></main>''')
    document, _ = extract_html(snapshot, collection=True)
    assert complete and not notes and document["complete"]
    assert "Second chapter wording." in " ".join(unit["text"] for unit in document["units"])
    assert calls == [URL]
    snapshot, complete, _ = run(f'<main><h1>Synthetic Regulation</h1><details><summary>Section 1</summary><p>{TEXT}</p></details></main>')
    assert complete and TEXT.encode() in snapshot.data


def test_guarded_browser_blocks_private_and_post_requests(browser_source):
    run, _, calls, _ = browser_source
    snapshot, complete, notes = run(f'''<main><h1>Synthetic Regulation</h1><p>{TEXT}</p></main>
      <script>fetch('https://127.0.0.1/private').catch(()=>{{}});
      fetch('/write',{{method:'POST'}}).catch(()=>{{}});</script>''')
    assert not complete and notes and calls == [URL]


def test_browser_keeps_archive_controls_outside_the_selected_document_body(browser_source):
    run, _, _, _ = browser_source
    snapshot, complete, notes = run(f'<main><p>This page has been archived.</p><details><summary>Table of Contents</summary><nav>Publisher navigation</nav></details><div id="regulation" class="docContents"><h1>Synthetic Regulation</h1><details><summary>Section 1</summary><p>{TEXT}</p></details></div></main>')
    body, _ = extract_html(snapshot, collection=True)
    text = " ".join(unit["text"] for unit in body["units"])
    assert complete and not notes and TEXT in text
    assert "archived" not in text and "Publisher navigation" not in text and "Table of Contents" not in text


def test_browser_request_limit_is_visible_and_does_not_fetch_another_document(browser_source, monkeypatch):
    run, _, calls, _ = browser_source
    monkeypatch.setattr(settings, "PDF_VALIDATION_BROWSER_MAX_REQUESTS", 1)
    _, complete, notes = run(f'<main><h1>Synthetic Regulation</h1><p>{TEXT}</p></main><script>fetch("/another-document").catch(()=>{{}})</script>')
    assert not complete and "request limit" in " ".join(notes) and calls == [URL]


def test_embedded_document_uses_only_configured_frame_content(browser_source):
    run, pages, _, _ = browser_source
    pages["https://publisher.example/rules/frame"] = f'<main><h1>Synthetic Regulation</h1><h2>Section 1</h2><p>{TEXT}</p></main>'
    markup = '<main><h1>Publisher catalog</h1><iframe id="document" src="frame"></iframe></main>'
    with pytest.raises(ValueError, match="no document sections"):
        run(markup)
    snapshot, complete, _ = run(markup, frame_selector="#document")
    assert complete and b"Publisher catalog" not in snapshot.data and TEXT.encode() in snapshot.data


def test_collection_invokes_configured_expansion_and_reports_unhandled_controls(browser_source):
    run, pages, _, fetch = browser_source
    run(f'<main><h1>Synthetic Regulation</h1><button id="expand" onclick="document.getElementById(\'wording\').hidden=false;this.remove()">Read document</button><section id="wording" hidden><h2>Section 1</h2><p>{TEXT}</p></section></main>',
        expand_selectors=["#expand"])
    result = collect_document(SourceSnapshot(pages[URL].encode(), URL, "html", "text/html"), ("publisher.example",), fetch)
    assert result["complete"] and result["source_coverage"]["method"] == "browser"
    _, complete, notes = run(f'<main><h1>Synthetic Regulation</h1><p>{TEXT}</p><select><option>Chapter</option></select></main>')
    assert not complete and notes


def test_browser_preserves_language_of_each_published_tab_panel(browser_source):
    run, _, _, _ = browser_source
    snapshot, complete, _ = run(f'''<main><h1>Synthetic Regulation</h1>
      <div role="tablist"><button role="tab" aria-controls="first">English</button>
      <button role="tab" aria-controls="second" onclick="document.getElementById('second').hidden=false">French</button></div>
      <section id="first" role="tabpanel" lang="en"><h2>Section 1</h2><p>{TEXT}</p></section>
      <section id="second" role="tabpanel" lang="fr" hidden><h2>Article 1</h2><p>Le rapport doit être présenté dans les trente jours et les documents doivent être conservés par les autorités.</p></section></main>''')
    body, _ = extract_html(snapshot, collection=True)
    assert complete
    assert any(unit.get("language") == "en" and TEXT in unit["text"] for unit in body["units"])
    assert any(unit.get("language") == "fr" and "trente jours" in unit["text"] for unit in body["units"])
