import urllib.request
from pathlib import Path

from margin.server import build_review_url, start_http_server


def test_start_http_server_serves_review_artifact(tmp_path: Path) -> None:
    site_root = tmp_path / "site"
    site_root.mkdir()
    review_path = site_root / "review.html"
    review_path.write_text("<h1>margin review</h1>\n", encoding="utf-8")

    server, thread, port = start_http_server(site_root, host="127.0.0.1", port=0)
    try:
        review_url = build_review_url("127.0.0.1", port, review_path.name)
        with urllib.request.urlopen(review_url, timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "margin review" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_build_review_url_returns_expected_path() -> None:
    assert build_review_url("127.0.0.1", 5174, "review.html") == "http://127.0.0.1:5174/review.html"
