from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
RISK_TAGS: set[str] = {
    "filesystem",
    "network",
    "account",
    "automation",
    "ocr",
    "yolo",
    "clipboard",
    "process",
}
COVER_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_MAX_COVER_BYTES = 512 * 1024
DEFAULT_MAX_ZIP_BYTES = 50 * 1024 * 1024
DEPENDENCY_FILES: set[str] = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pipfile",
    "pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
    "environment.yml",
    "environment.yaml",
}
EXCLUDED_NAMES: set[str] = {"__pycache__", ".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES: set[str] = {".pyc", ".pyo"}

FACTORY_FILE_NAME = "factory.py"
CONST_FILE_NAME = "const.py"
APP_SETTING_FILE_NAME = "app_setting.py"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def is_factory_file(name: str) -> bool:
    """与主程序一致：推荐 ``factory.py``，旧写法 ``*_factory.py`` 兼容。"""
    return name == FACTORY_FILE_NAME or name.endswith("_" + FACTORY_FILE_NAME)


def is_const_file(name: str) -> bool:
    """与主程序一致：推荐 ``const.py``，旧写法 ``*_const.py`` 兼容。"""
    return name == CONST_FILE_NAME or name.endswith("_" + CONST_FILE_NAME)


def is_app_setting_file(name: str) -> bool:
    return name == APP_SETTING_FILE_NAME or name.endswith("_" + APP_SETTING_FILE_NAME)


def top_level_py_files(package_dir: Path) -> list[Path]:
    return sorted(path for path in package_dir.glob("*.py") if path.is_file())


def find_const_files(package_dir: Path) -> list[Path]:
    return [path for path in top_level_py_files(package_dir) if is_const_file(path.name)]


def find_factory_files(package_dir: Path) -> list[Path]:
    return [path for path in top_level_py_files(package_dir) if is_factory_file(path.name)]


def has_factory_and_const(package_dir: Path) -> bool:
    return bool(find_factory_files(package_dir)) and bool(find_const_files(package_dir))


def find_package_dirs(repo: Path) -> list[Path]:
    """插件包目录：非隐藏子目录，第一层同时有工厂文件和常量文件。

    判据与主程序一致，plugin.json 不参与判定（缺少时由校验单独报错）。
    """
    return sorted(
        child
        for child in repo.iterdir()
        if child.is_dir() and not child.name.startswith(".") and has_factory_and_const(child)
    )


def find_package_dir(repo: Path) -> Path:
    candidates = find_package_dirs(repo)
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise ValueError(
            f"expected exactly one subdirectory with factory and const files in {repo}, found: {names}"
        )
    return candidates[0]


def read_const_value(const_path: Path, name: str) -> Any:
    """用 ast 读取常量文件里的字面量赋值，不 import；缺失或不是字面量时返回 None。"""
    try:
        tree = ast.parse(const_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    value: Any = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                value = None
    return value


def app_id_from_const(package_dir: Path) -> str:
    """包目录常量文件里的 ``APP_ID``，运行时身份只认它；读不到返回空串。"""
    consts = find_const_files(package_dir)
    if len(consts) != 1:
        return ""
    value = read_const_value(consts[0], "APP_ID")
    return value if isinstance(value, str) else ""


def plugin_id(manifest: dict[str, Any]) -> str:
    value = manifest.get("id")
    return value if isinstance(value, str) else ""


def is_dependency_file(name: str) -> bool:
    lower = name.lower()
    return lower in DEPENDENCY_FILES or (
        lower.startswith("requirements") and lower.endswith(".txt")
    )


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_NAMES for part in path.parts) or (
        path.suffix in EXCLUDED_SUFFIXES
    )
