"""飞书 CLI 的最小参数数组执行器；不记录命令参数或输出。"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class CliResponse:
    returncode: int
    stdout: str
    stderr: str = ""


class CliRunner(Protocol):
    def run(self, argv: Sequence[str], *, stdin: str | None = None) -> CliResponse: ...

    def upload(self, argv: Sequence[str], *, payload: bytes, name: str) -> CliResponse: ...


class SubprocessCliRunner:
    """以参数数组调用 CLI，绝不经由 shell。"""

    def run(self, argv: Sequence[str], *, stdin: str | None = None) -> CliResponse:
        return self._run(argv, stdin=stdin)

    @staticmethod
    def _run(argv: Sequence[str], *, stdin: str | None = None, cwd: str | None = None) -> CliResponse:
        try:
            completed = subprocess.run(
                list(argv),
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                input=stdin,
                timeout=30,
                cwd=cwd,
            )
        except FileNotFoundError:
            return CliResponse(127, "", "lark-cli not found")
        except subprocess.TimeoutExpired:
            return CliResponse(124, "", "lark-cli timed out")
        return CliResponse(completed.returncode, completed.stdout, completed.stderr)

    def upload(self, argv: Sequence[str], *, payload: bytes, name: str) -> CliResponse:
        safe_name = Path(name).name
        if safe_name != name or not safe_name:
            return CliResponse(2, "", "unsafe upload name")
        with tempfile.TemporaryDirectory(prefix="zsk-upload-") as directory:
            path = Path(directory) / safe_name
            path.write_bytes(payload)
            relative_path = f"./{safe_name}"
            return self._run(tuple(relative_path if part == "{file}" else part for part in argv), cwd=directory)


@dataclass(frozen=True)
class RecordedCliCall:
    """测试用的脱敏录制响应；argv 必须逐项匹配。"""

    argv: tuple[str, ...]
    stdout: str
    returncode: int = 0
    stderr: str = ""
    stdin: str | None = None
    payload: bytes | None = None
    upload_name: str | None = None


class RecordedCliRunner:
    """声明式 fake runner，不执行外部 CLI。"""

    def __init__(self, calls: Sequence[RecordedCliCall]) -> None:
        self._calls = tuple(calls)
        self._cursor = 0
        self.calls: list[tuple[str, ...]] = []

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._calls)

    def run(self, argv: Sequence[str], *, stdin: str | None = None) -> CliResponse:
        actual = tuple(argv)
        self.calls.append(actual)
        if self._cursor >= len(self._calls):
            return CliResponse(2, "", "unexpected lark-cli call")
        expected = self._calls[self._cursor]
        self._cursor += 1
        if actual != expected.argv or stdin != expected.stdin:
            return CliResponse(2, "", "unexpected lark-cli arguments")
        return CliResponse(expected.returncode, expected.stdout, expected.stderr)

    def upload(self, argv: Sequence[str], *, payload: bytes, name: str) -> CliResponse:
        actual = tuple(argv)
        self.calls.append(actual)
        if self._cursor >= len(self._calls):
            return CliResponse(2, "", "unexpected lark-cli upload")
        expected = self._calls[self._cursor]
        self._cursor += 1
        if actual != expected.argv or payload != expected.payload or name != expected.upload_name:
            return CliResponse(2, "", "unexpected lark-cli upload arguments")
        return CliResponse(expected.returncode, expected.stdout, expected.stderr)
