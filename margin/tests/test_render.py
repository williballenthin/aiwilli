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
