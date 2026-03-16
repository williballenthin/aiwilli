from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Literal,
    Name,
    Operator,
    Text,
    Whitespace,
)
from pygments.util import ClassNotFound

from margin.models import SourceFile, SourceSnapshot

logger = logging.getLogger(__name__)


class MarginSyntaxStyle(Style):  # type: ignore[misc]
    background_color = "transparent"
    highlight_color = "var(--code-highlight)"
    styles = {
        Text: "var(--code-text)",
        Whitespace: "var(--code-muted)",
        Error: "border:var(--danger)",
        Comment: "italic var(--code-comment)",
        Keyword: "var(--code-keyword)",
        Keyword.Type: "var(--code-type)",
        Operator: "var(--code-operator)",
        Operator.Word: "var(--code-keyword)",
        Name.Builtin: "var(--code-builtin)",
        Name.Function: "var(--code-function)",
        Name.Class: "var(--code-type)",
        Name.Namespace: "var(--code-type)",
        Name.Exception: "var(--code-type)",
        Name.Decorator: "var(--code-decorator)",
        Name.Attribute: "var(--code-attribute)",
        Name.Tag: "var(--code-tag)",
        Name.Constant: "var(--code-constant)",
        Literal.Number: "var(--code-number)",
        Literal.String: "var(--code-string)",
        Literal.String.Doc: "italic var(--code-doc)",
        Literal.String.Interpol: "var(--code-constant)",
        Literal.String.Regex: "var(--code-regex)",
        Generic.Deleted: "var(--danger)",
        Generic.Inserted: "var(--reviewed)",
        Generic.Heading: "var(--code-type)",
        Generic.Subheading: "var(--code-type)",
        Generic.Prompt: "var(--code-muted)",
        Generic.Output: "var(--code-muted)",
        Generic.Traceback: "var(--danger)",
    }


FORMATTER = HtmlFormatter(nowrap=True, style=MarginSyntaxStyle, classprefix="tok-")
TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader(str(resources.files("margin").joinpath("templates"))),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_review_document(snapshot: SourceSnapshot) -> str:
    """Render a self-contained HTML review document.

    Args:
        snapshot: Source snapshot to render.
    """
    review_data = build_review_data(snapshot)
    template = TEMPLATE_ENVIRONMENT.get_template("review.html.j2")
    return template.render(
        page_title=snapshot.title,
        source_label=snapshot.source_label,
        snapshot_id=snapshot.snapshot_id,
        generated_at=snapshot.generated_at.isoformat(),
        file_count=len(snapshot.files),
        syntax_css=FORMATTER.get_style_defs(".syntax"),
        snapshot_json=render_embedded_json(review_data),
    )


def build_review_data(snapshot: SourceSnapshot) -> dict[str, Any]:
    """Build browser-side snapshot data.

    Args:
        snapshot: Source snapshot to render.
    """
    return {
        "title": snapshot.title,
        "sourceKind": snapshot.source_kind,
        "sourceLabel": snapshot.source_label,
        "snapshotId": snapshot.snapshot_id,
        "generatedAt": snapshot.generated_at.isoformat(),
        "files": [render_source_file(file) for file in snapshot.files],
    }


def render_source_file(file: SourceFile) -> dict[str, Any]:
    """Render one file into line-oriented highlighted HTML.

    Args:
        file: Source file to render.
    """
    lexer = get_lexer(file)
    language = lexer.name
    highlighted = highlight(file.text, lexer, FORMATTER)
    highlighted_lines = highlighted.splitlines()
    raw_lines = file.text.splitlines()
    if len(highlighted_lines) != len(raw_lines):
        logger.debug(
            "Highlight line mismatch for %s: %s highlighted vs %s raw",
            file.path,
            len(highlighted_lines),
            len(raw_lines),
        )
        highlighted_lines = [highlight(line, lexer, FORMATTER).rstrip("\n") for line in raw_lines]
    return {
        "path": file.path,
        "language": language,
        "lineCount": len(raw_lines),
        "contentDigest": file.content_digest,
        "lines": highlighted_lines,
    }


def get_lexer(file: SourceFile) -> Any:
    """Choose a syntax lexer for a file.

    Args:
        file: Source file.
    """
    try:
        return get_lexer_for_filename(file.path, file.text)
    except ClassNotFound:
        return TextLexer()


def render_embedded_json(data: dict[str, Any]) -> str:
    """Serialize JSON for safe embedding in a script tag.

    Args:
        data: JSON-serializable payload.
    """
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
