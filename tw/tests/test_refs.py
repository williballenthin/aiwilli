"""Tests for references extraction."""

from tw.refs import extract_refs


class TestExtractRefs:
    def test_no_refs(self) -> None:
        text = "This is some text without any references."
        assert extract_refs(text, "PROJ") == []

    def test_single_ref(self) -> None:
        text = "See PROJ-1 for details."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]

    def test_multiple_refs(self) -> None:
        text = "Related to PROJ-1, PROJ-2-1, and PROJ-3-1a."
        assert extract_refs(text, "PROJ") == ["PROJ-1", "PROJ-2-1", "PROJ-3-1a"]

    def test_sorted_output(self) -> None:
        text = "See PROJ-10, PROJ-2, PROJ-1."
        assert extract_refs(text, "PROJ") == ["PROJ-1", "PROJ-2", "PROJ-10"]

    def test_deduplicated(self) -> None:
        text = "PROJ-1 is related to PROJ-1."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]

    def test_different_prefix(self) -> None:
        text = "See AUTH-1 and AUTH-2-1."
        assert extract_refs(text, "AUTH") == ["AUTH-1", "AUTH-2-1"]

    def test_ignores_other_prefixes(self) -> None:
        text = "See PROJ-1 and OTHER-2."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]
