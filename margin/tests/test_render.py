from datetime import UTC, datetime

from margin.models import SourceFile, SourceSnapshot
from margin.render import render_review_document


def test_render_review_document_escapes_embedded_snapshot_json() -> None:
    snapshot = SourceSnapshot(
        title="Demo review",
        source_kind="local",
        source_label="/tmp/demo",
        snapshot_id="sha256:test",
        generated_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        files=[
            SourceFile(
                path="src/app.js",
                text='const marker = "</script>";\n',
                content_digest="abc123",
            )
        ],
    )

    document = render_review_document(snapshot)

    assert document.count("</script>") == 2
    assert "src/app.js" in document
    assert "Demo review" in document


def test_render_review_document_includes_mobile_and_notes_ui() -> None:
    snapshot = SourceSnapshot(
        title="Demo review",
        source_kind="local",
        source_label="/tmp/demo",
        snapshot_id="sha256:test",
        generated_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        files=[
            SourceFile(
                path="src/app.py",
                text="print('ok')\n",
                content_digest="abc123",
            )
        ],
    )

    document = render_review_document(snapshot)

    assert 'id="mobile-panel-nav"' in document
    assert 'id="note-stack"' in document
    assert 'id="sidebar-actions-menu"' in document
    assert 'id="mark-reviewed"' in document
    assert 'id="flag-followup"' in document
    assert 'data-panel="comments"' not in document
    assert 'id="comment-title"' not in document
    assert 'id="comment-list"' not in document


def test_render_review_document_uses_theme_aware_syntax_palette() -> None:
    snapshot = SourceSnapshot(
        title="Demo review",
        source_kind="local",
        source_label="/tmp/demo",
        snapshot_id="sha256:test",
        generated_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        files=[
            SourceFile(
                path="src/app.py",
                text="def demo() -> str:\n    return 'ok'\n",
                content_digest="abc123",
            )
        ],
    )

    document = render_review_document(snapshot)

    assert "--code-bg: #f4f7fc;" in document
    assert "--code-bg: #111923;" in document
    assert ".syntax { background: transparent; color: var(--code-text) }" in document
    assert "var(--code-keyword)" in document
    assert "var(--code-string)" in document
    assert "font-weight: bold" not in document
    assert "#f8f8f8" not in document


def test_render_review_document_uses_flat_cards_and_enter_submit_composer() -> None:
    snapshot = SourceSnapshot(
        title="Demo review",
        source_kind="local",
        source_label="/tmp/demo",
        snapshot_id="sha256:test",
        generated_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        files=[
            SourceFile(
                path="src/app.py",
                text="print('ok')\n",
                content_digest="abc123",
            )
        ],
    )

    document = render_review_document(snapshot)

    assert 'event.key !== "Enter" || event.shiftKey || event.isComposing' in document
    assert ".note-composer-card textarea {" in document
    assert "margin-top: 0.3rem;" in document
    assert "border-radius: 0.8rem;" not in document
    assert "border-radius: 0.75rem;" not in document
    assert "border-radius: 0.6rem;" not in document
    assert "border-radius: 999px;" not in document
