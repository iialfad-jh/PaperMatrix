from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

collect_ignore = ["test_api.py"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTEST_ARTIFACT_DIRS = (
    PROJECT_ROOT / ".pytest_cache",
    PROJECT_ROOT / ".pytest_tmp",
)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def make_writable_and_retry(func, failed_path, _exc_info):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except OSError:
            pass

    shutil.rmtree(path, onerror=make_writable_and_retry)


def _clean_pytest_artifacts() -> None:
    for path in PYTEST_ARTIFACT_DIRS:
        _remove_tree(path)


def pytest_sessionstart(session):
    _clean_pytest_artifacts()


def pytest_unconfigure(config):
    _clean_pytest_artifacts()
