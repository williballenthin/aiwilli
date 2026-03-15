from pathlib import Path

from margin.app import LocalBuildRequest, build_local_review


def test_build_local_review_writes_html_artifact(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    output_path = tmp_path / "review.html"
    result = build_local_review(
        LocalBuildRequest(
            root=root,
            output_path=output_path,
            title="Demo review",
            open_browser=False,
        )
    )

    assert result.output_path == output_path
    assert result.file_count == 1
    content = output_path.read_text(encoding="utf-8")
    assert "Demo review" in content
    assert "src/app.py" in content
    assert result.snapshot_id in content
