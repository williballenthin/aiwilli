"""Shared pytest fixtures."""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test-local resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def taskwarrior_env(temp_dir: Path) -> Generator[dict[str, str], None, None]:
    """Provide isolated TaskWarrior environment.

    Creates a temporary TASKDATA directory and configures UDAs.
    """
    taskdata = temp_dir / "task"
    taskdata.mkdir()

    env = os.environ.copy()
    env["TASKDATA"] = str(taskdata)
    env["TASKRC"] = str(temp_dir / "taskrc")

    # Create minimal taskrc with UDAs
    taskrc_content = """
data.location={}
uda.tw_type.type=string
uda.tw_type.label=Type
uda.tw_id.type=string
uda.tw_id.label=TW ID
uda.tw_parent.type=string
uda.tw_parent.label=Parent
uda.tw_body.type=string
uda.tw_body.label=Body
uda.tw_refs.type=string
uda.tw_refs.label=Refs
uda.tw_status.type=string
uda.tw_status.label=TW Status
""".format(taskdata)

    (temp_dir / "taskrc").write_text(taskrc_content)

    yield env
