"""语言运行器注册表。"""

from app.domains.executions.languages.base import LanguageRunner
from app.domains.executions.languages.python_runner import PythonRunner

_RUNNERS: dict[str, LanguageRunner] = {}


def register_runner(runner: LanguageRunner) -> None:
    _RUNNERS[runner.language] = runner


def get_runner(language: str) -> LanguageRunner | None:
    return _RUNNERS.get(language)


def list_languages() -> list[str]:
    return sorted(_RUNNERS)


# 内置注册（C++ 在 P4.2c 以同协议接入）
register_runner(PythonRunner())
