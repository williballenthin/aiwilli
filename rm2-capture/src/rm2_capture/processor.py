import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL = "gemini/gemini-3-flash-preview"

PROMPT = """Transcribe this handwritten note verbatim. Output ONLY a single markdown
code block containing the transcription. Preserve the structure including:
- Bullet points and indentation
- Tables (as markdown tables)
- Paragraphs

Its ok to rejoin/wrap lines if it appears the original text was wrapping, but
maintain line breaks if they indicate structure or format.

Do not add any commentary, analysis, or text outside the code block."""


class TranscriptionError(Exception):
    pass


class Processor:
    def transcribe_pdf(self, pdf_path: Path) -> str:
        """
        Transcribe a PDF using the llm CLI tool.

        Raises:
            TranscriptionError: If llm invocation fails or response parsing fails.
        """
        logger.debug(f"Transcribing {pdf_path} with model {MODEL}")

        try:
            result = subprocess.run(
                ["llm", "-m", MODEL, "-a", str(pdf_path), PROMPT],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise TranscriptionError(f"llm command failed: {e.stderr}") from e
        except FileNotFoundError as e:
            raise TranscriptionError("llm command not found - is it installed?") from e

        return self._extract_markdown(result.stdout)

    def _extract_markdown(self, response: str) -> str:
        match = re.search(r"```(?:markdown)?\n(.*?)```", response, re.DOTALL)
        if not match:
            raise TranscriptionError("No markdown code block found in response")
        return match.group(1).strip()
