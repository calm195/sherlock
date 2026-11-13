"""Sherlock 包的初始化模块。

定义包名称、版本信息及发布版本查询地址。
"""

from importlib.metadata import version as pkg_version, PackageNotFoundError
import pathlib
import tomli


def get_version() -> str:
    """获取已安装包的版本号；缺少安装元数据时读取 pyproject.toml。"""
    try:
        return pkg_version("sherlock_project")
    except PackageNotFoundError:
        pyproject_path: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject_path.open("rb") as f:
            pyproject_data = tomli.load(f)
        return pyproject_data["project"]["version"]

# 此变量仅用于检测直接运行脚本（未按模块或包运行）时产生的 ImportError。
import_error_test_var = None

__shortname__   = "Sherlock"
__longname__    = "Sherlock: Find Usernames Across Social Networks"
__version__     = get_version()

forge_api_latest_release = "https://api.github.com/repos/sherlock-project/sherlock/releases/latest"
