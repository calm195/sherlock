import os
from sherlock_interactives import Interactives
import sherlock_project

def test_version_without_installed_metadata(monkeypatch) -> None:
    expected_version = sherlock_project.get_version()

    def missing_version(package_name):
        raise sherlock_project.PackageNotFoundError(package_name)

    monkeypatch.setattr(sherlock_project, "pkg_version", missing_version)
    assert sherlock_project.get_version() == expected_version

def test_versioning() -> None:
    # 确认 __version__ 与向用户展示的版本一致。
    assert sherlock_project.__version__ in Interactives.run_cli("--version")
    # 确认包内的 __version__ 仅在 __init__ 中定义。
    found:list = Interactives.walk_sherlock_for_files_with(r'__version__ *= *')
    expected:list = [
        # Windows 下必须规范化路径，处理 / 与反斜杠的差异。
        os.path.normpath("sherlock_project/__init__.py"),
    ]
    # macOS 下必须排序后再比较。
    assert sorted(found) == sorted(expected)
