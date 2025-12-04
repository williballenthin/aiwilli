"""Tests for ID utilities."""

from tw.ids import (
    generate_next_epic_id,
    generate_next_story_id,
    generate_next_task_id,
    parse_id,
    parse_id_sort_key,
    sort_ids,
)


class TestParseId:
    def test_epic_id(self) -> None:
        result = parse_id("PROJ-1")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num is None
        assert result.task_suffix is None

    def test_story_id(self) -> None:
        result = parse_id("PROJ-1-2")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num == 2
        assert result.task_suffix is None

    def test_task_id(self) -> None:
        result = parse_id("PROJ-1-2a")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num == 2
        assert result.task_suffix == "a"

    def test_task_id_double_letter(self) -> None:
        result = parse_id("PROJ-1-2aa")
        assert result.task_suffix == "aa"

    def test_invalid_id(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Invalid tw_id format"):
            parse_id("invalid")


class TestSortIds:
    def test_sort_mixed(self) -> None:
        ids = [
            "PROJ-12",
            "PROJ-2",
            "PROJ-1-10",
            "PROJ-1-2",
            "PROJ-1",
            "PROJ-1-1a",
            "PROJ-1-1b",
            "PROJ-1-1aa",
            "PROJ-1-1",
            "PROJ-2-1",
        ]
        expected = [
            "PROJ-1",
            "PROJ-1-1",
            "PROJ-1-1a",
            "PROJ-1-1b",
            "PROJ-1-1aa",
            "PROJ-1-2",
            "PROJ-1-10",
            "PROJ-2",
            "PROJ-2-1",
            "PROJ-12",
        ]
        assert sort_ids(ids) == expected


class TestParseIdSortKey:
    def test_ordering(self) -> None:
        assert parse_id_sort_key("PROJ-1") < parse_id_sort_key("PROJ-2")
        assert parse_id_sort_key("PROJ-1-1") < parse_id_sort_key("PROJ-1-2")
        assert parse_id_sort_key("PROJ-1-1a") < parse_id_sort_key("PROJ-1-1b")
        assert parse_id_sort_key("PROJ-1-1b") < parse_id_sort_key("PROJ-1-1aa")
        assert parse_id_sort_key("PROJ-1-2") < parse_id_sort_key("PROJ-1-10")


class TestGenerateNextEpicId:
    def test_first_epic(self) -> None:
        existing: list[str] = []
        assert generate_next_epic_id("PROJ", existing) == "PROJ-1"

    def test_sequential(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-3"

    def test_with_gap(self) -> None:
        existing = ["PROJ-1", "PROJ-5"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-6"

    def test_with_reserved_from_orphan(self) -> None:
        existing = ["PROJ-1", "PROJ-2", "PROJ-3-1"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-4"


class TestGenerateNextStoryId:
    def test_first_story(self) -> None:
        existing: list[str] = []
        assert generate_next_story_id("PROJ-1", existing) == "PROJ-1-1"

    def test_sequential(self) -> None:
        existing = ["PROJ-1-1", "PROJ-1-2"]
        assert generate_next_story_id("PROJ-1", existing) == "PROJ-1-3"

    def test_orphan_story(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_story_id(None, existing, prefix="PROJ") == "PROJ-3"

    def test_orphan_story_with_children(self) -> None:
        existing = ["PROJ-1", "PROJ-2", "PROJ-2-1", "PROJ-2-2"]
        assert generate_next_story_id("PROJ-2", existing) == "PROJ-2-3"


class TestGenerateNextTaskId:
    def test_first_task(self) -> None:
        existing: list[str] = []
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1a"

    def test_sequential(self) -> None:
        existing = ["PROJ-1-1a", "PROJ-1-1b"]
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1c"

    def test_after_z(self) -> None:
        existing = [f"PROJ-1-1{chr(ord('a') + i)}" for i in range(26)]
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1aa"

    def test_after_az(self) -> None:
        existing = [f"PROJ-1-1{chr(ord('a') + i)}" for i in range(26)]
        existing.extend([f"PROJ-1-1a{chr(ord('a') + i)}" for i in range(26)])
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1ba"

    def test_orphan_task(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_task_id(None, existing, prefix="PROJ") == "PROJ-3"

    def test_task_under_orphan_story(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_task_id("PROJ-2", existing) == "PROJ-2-1"

    def test_task_under_orphan_story_sequential(self) -> None:
        existing = ["PROJ-1", "PROJ-2", "PROJ-2-1", "PROJ-2-2"]
        assert generate_next_task_id("PROJ-2", existing) == "PROJ-2-3"
