import pytest

from rm2_capture.processor import Processor, TranscriptionError


@pytest.fixture
def processor():
    return Processor()


class TestExtractMarkdown:
    def test_extracts_markdown_from_fenced_block(self, processor):
        response = """Here's the transcription:

```markdown
# Meeting Notes

- Point 1
- Point 2
```

That's all!"""

        result = processor._extract_markdown(response)

        assert result == "# Meeting Notes\n\n- Point 1\n- Point 2"

    def test_extracts_markdown_without_language_specifier(self, processor):
        response = """```
Just plain text
with multiple lines
```"""

        result = processor._extract_markdown(response)

        assert result == "Just plain text\nwith multiple lines"

    def test_raises_when_no_fence_found(self, processor):
        response = "No code block here, just plain text."

        with pytest.raises(TranscriptionError) as exc_info:
            processor._extract_markdown(response)

        assert "No markdown code block found" in str(exc_info.value)

    def test_extracts_first_fence_when_multiple_present(self, processor):
        response = """```
First block
```

```
Second block
```"""

        result = processor._extract_markdown(response)

        assert result == "First block"

    def test_handles_nested_backticks_in_content(self, processor):
        response = """```markdown
Use `code` like this
```"""

        result = processor._extract_markdown(response)

        assert result == "Use `code` like this"
