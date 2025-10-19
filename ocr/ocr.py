# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "docling[vlm]",
#     "requests",
#     "rich",
# ]
# ///
"""OCR + page break fixing in two passes: OCR → Stitch."""

import sys
import re
import requests
import rich

from docling.datamodel import vlm_model_specs
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import VlmPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline

# LM Studio API endpoint (default)
LM_STUDIO_URL = "http://localhost:1234/v1/completions"
LM_STUDIO_MODEL = "openai/gpt-oss-20b"

def debug(msg: str) -> None:
    """Print debug message to stderr."""
    rich.print(msg, file=sys.stderr)

def ocr_pass(sources: list[str]) -> str:
    """Convert sources to merged HTML."""
    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_model_specs.GRANITEDOCLING_MLX,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline,
                pipeline_options=pipeline_options,
            ),
            InputFormat.IMAGE: ImageFormatOption(
                pipeline_cls=VlmPipeline,
                pipeline_options=pipeline_options,
            ),
        }
    )

    html_parts = []
    for source in sources:
        debug(f"[gray69]Processing: {source}[/gray69]")
        result = converter.convert(source=source)
        doc_html = result.document.export_to_html()
        html_parts.append(doc_html)

    # Merge HTML documents
    if len(html_parts) == 1:
        return html_parts[0]

    first_doc_html = html_parts[0]
    header_end = first_doc_html.find("<body>") + len("<body>")
    header = first_doc_html[:header_end]
    footer = first_doc_html.rfind("</body>")
    base_footer = first_doc_html[footer:]

    body_content = []
    for html in html_parts:
        body_start = html.find("<div class='page'>")
        body_end = html.rfind("</div>") + len("</div>")
        if body_start != -1 and body_end > body_start:
            body_content.append(html[body_start:body_end])

    merged_html = header + "\n".join(body_content) + base_footer
    return merged_html

def find_page_break(content: str) -> tuple[int, str] | None:
    """Find the first page break pattern and return (position, match_string)."""
    pattern = r"</p>\n</div>\n<div class='page'>\n<p>"
    match = re.search(pattern, content)
    if match:
        return (match.start(), match.group())
    return None

def extract_context(content: str, match_pos: int, match_string: str, context_chars: int = 256) -> str:
    """Extract context around the match (N characters before and after)."""
    before_start = max(0, match_pos - context_chars)
    before_context = content[before_start:match_pos].rpartition("<p>")[2]

    after_start = match_pos + len(match_string)
    after_end = min(len(content), after_start + context_chars)
    after_context = content[after_start:after_end].partition("</p>")[0]

    context = f"{before_context}\n<page break />\n{after_context}"

    return context

def call_lm_studio(context: str) -> str | None:
    """Call LM Studio API and get response."""
    prompt = f"""Given this HTML snippet with a page break (`<div class='page'>`):

```
...
{context}
...
```

Question: Should the paragraphs split by the page break be merged, or should they remain two separate paragraphs?
Focus on the text just before and after `</div><div class='page'>`. This is the page break.

The text comes from long-form English, so expect sentences to end with punctuation.
There's also dialog, so use hints like the speaker to decide if paragraphs should be split or merged.

Respond with either "true" (merge) or "false" (keep separate). End your response with either "answer true" or "answer false".
"""
    try:
        response = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "prompt": prompt,
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()

        if 'choices' in result and len(result['choices']) > 0:
            text = result['choices'][0].get('text', '').strip()
            debug(f"[gray69]LM Studio response: [/gray69][green]{text}[/green]")
            return text
        else:
            debug(f"[red]Unexpected response format: {result}[/red]")
            return None

    except Exception as e:
        debug(f"[red]Error calling LM Studio: {e}[/red]")
        return None

def get_llm_decision(context: str) -> bool | None:
    """Keep prompting LLM until we get a valid "true" or "false" response."""
    max_attempts = 5
    attempt = 0

    while attempt < max_attempts:
        attempt += 1

        response = call_lm_studio(context)
        if response is None:
            debug(f"[yellow]No response from LLM, retrying...[/yellow]")
            continue

        response = response.lower().strip().rstrip(".")

        if response.endswith("answer true"):
            debug(f"[gray69]LLM decision: [/gray69][blue]MERGE paragraphs (true)[/blue]")
            return True
        if response.endswith("answer false"):
            debug(f"[gray69]LLM decision: [/gray69][cyan]KEEP SEPARATE paragraphs (false)[/cyan]")
            return False
        else:
            debug(f"[yellow]Invalid response '{response}', retrying...[/yellow]")

    debug(f"[red]Failed to get valid response after {max_attempts} attempts[/red]")
    return None

def stitch_pass(content: str) -> str:
    """Fix page breaks with LLM guidance."""
    debug(f"[gray69]Starting stitch pass[/gray69]")

    for i in range(1000):
        debug(f"[gray69]pass: {i}[/gray69]")

        result = find_page_break(content)
        if result is None:
            debug(f"[gray69]all pages merged[/gray69]")
            break

        match_pos, match_string = result

        context = extract_context(content, match_pos, match_string, context_chars=256)
        debug(f"[gray69]Context extracted:\n[/gray69][default]{context}[/default]\n")

        should_merge = get_llm_decision(context)
        if should_merge is None:
            debug(f"[red]Error: Could not get valid LLM response[/red]")
            sys.exit(1)

        if should_merge:
            debug(f"[gray69]Removing page break (merging paragraphs)[/gray69]")
            updated_content = content[:match_pos] + " " + content[match_pos + len(match_string):]
        else:
            debug(f"[gray69]Replacing page break with paragraph marker[/gray69]")
            updated_content = content[:match_pos] + "</p><p>" + content[match_pos + len(match_string):]

        content = updated_content
        debug("")
        debug("")

    # via: https://iangmcdowell.com/blog/posts/laying-out-a-book-with-css/
    content = content.replace("<style>", """<style>
h2 {
    text-align: center;
    font-family: "Jost";  
    margin-top: 1.4in;
    margin-bottom: .9in;
    font-weight: 300;
    display: inline-block; 
    /* Pad box to position the "underline" that's rendered using the border */
    padding: 0.1in 0.2in;
    border-bottom: 1px solid;
    line-height: 1em;
    font-size: 24pt;
}

p {
    margin:0;
    text-indent: 1.5em;
    font-size: 15pt;
    line-height: 19pt;
    text-align: justify;
    text-justify: inter-word;
    word-spacing: -.7px;
}

@media print {
  h2 { 
    break-before: page;
  }
}

<!--""")
    content = content.replace("</style>", "--> </style>")

    return content

def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: ocr.py <image1.png> [image2.png ...]", file=sys.stderr)
        sys.exit(1)

    sources = sys.argv[1:]

    # Pass 1: OCR
    debug(f"[gray69]Pass 1: OCR processing[/gray69]")
    html = ocr_pass(sources)
    debug(f"[gray69]OCR complete, HTML size: {len(html)} bytes[/gray69]")
    debug("")

    # Pass 2: Stitch
    debug(f"[gray69]Pass 2: Stitch fixup[/gray69]")
    html = stitch_pass(html)
    debug(f"[gray69]Stitch complete[/gray69]")

    # Output
    sys.stdout.write(html)

if __name__ == "__main__":
    main()
