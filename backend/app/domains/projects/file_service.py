"""项目文件的业务逻辑：路径校验、CRUD、初始脚手架。

安全约束（设计文档 15.2 精神：所有外部输入先视为不可信）：
- 路径必须是相对路径，禁止绝对路径、`..` 段、反斜杠、控制字符；
- Windows 保留名与非法字符一并拒绝，保证未来可安全落盘；
- 内容与文件数量有上限，防止资源滥用。
"""

import hashlib
import re

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.domains.projects.models import CodeSnapshot, Project, ProjectFile

MAX_PATH_LENGTH = 500
MAX_CONTENT_CHARS = 1_000_000
MAX_FILES_PER_PROJECT = 2000
SNAPSHOTS_PER_FILE_LIMIT = 50

_ILLEGAL_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class FileError(Exception):
    """文件操作的可预期错误（映射为 4xx）。"""

    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


class FileNotFound(FileError):
    def __init__(self, path: str) -> None:
        super().__init__(f"file not found: {path}", status=404)


def sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_path(path: str) -> str:
    """校验相对路径；不合法即抛 FileError(422)。不做静默归一化。"""
    if not path or not path.strip():
        raise FileError("文件路径不能为空")
    if path != path.strip():
        raise FileError("路径不能以空格开头或结尾")
    candidate = path
    if len(candidate) > MAX_PATH_LENGTH:
        raise FileError(f"路径过长（上限 {MAX_PATH_LENGTH} 字符）")
    if "\\" in candidate:
        raise FileError("路径分隔符必须使用 /")
    if candidate.startswith("/"):
        raise FileError("不允许绝对路径")
    if _ILLEGAL_CHARS.search(candidate):
        raise FileError("路径包含非法字符")
    segments = candidate.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise FileError("路径段不能为空、. 或 ..")
        if segment != segment.strip():
            raise FileError("路径段不能以空格开头或结尾")
        if segment.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise FileError(f"{segment} 是保留名称")
    return candidate


def _get_file(db: Session, project_id, path: str) -> ProjectFile:
    stmt = select(ProjectFile).where(
        ProjectFile.project_id == project_id, ProjectFile.path == path
    )
    file = db.scalar(stmt)
    if file is None:
        raise FileNotFound(path)
    return file


def list_files(db: Session, project_id) -> list[ProjectFile]:
    stmt = (
        select(ProjectFile)
        .where(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.path)
    )
    return list(db.scalars(stmt))


def read_file(db: Session, project_id, path: str) -> ProjectFile:
    return _get_file(db, project_id, validate_path(path))


def _snapshot_old_content(db: Session, project_id, path: str, old_content: str) -> None:
    """把被覆盖的旧内容写入快照，并裁剪超出上限的历史。"""
    db.add(
        CodeSnapshot(
            project_id=project_id,
            path=path,
            content=old_content,
            content_sha256=sha256_hex(old_content),
        )
    )
    # 会话为 autoflush=False，需显式 flush 让裁剪子查询看到刚插入的快照。
    db.flush()
    keep_ids = (
        select(CodeSnapshot.id)
        .where(CodeSnapshot.project_id == project_id, CodeSnapshot.path == path)
        .order_by(CodeSnapshot.created_at.desc(), CodeSnapshot.id.desc())
        .limit(SNAPSHOTS_PER_FILE_LIMIT)
    )
    db.execute(
        delete(CodeSnapshot).where(
            CodeSnapshot.project_id == project_id,
            CodeSnapshot.path == path,
            CodeSnapshot.id.not_in(keep_ids),
        )
    )


def write_file(db: Session, project_id, path: str, content: str) -> tuple[ProjectFile, bool]:
    """创建或整体替换文件，返回 (文件, 是否新建)。

    覆盖已有文件时，旧内容（若与新内容不同）先进入快照历史。
    """
    safe_path = validate_path(path)
    if len(content) > MAX_CONTENT_CHARS:
        raise FileError(f"文件内容超过上限（{MAX_CONTENT_CHARS} 字符）")
    file = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id, ProjectFile.path == safe_path
        )
    )
    created = file is None
    if created:
        total = db.scalar(
            select(func.count()).select_from(ProjectFile).where(
                ProjectFile.project_id == project_id
            )
        )
        if (total or 0) >= MAX_FILES_PER_PROJECT:
            raise FileError(f"项目文件数量超过上限（{MAX_FILES_PER_PROJECT}）")
        file = ProjectFile(project_id=project_id, path=safe_path, content=content)
        db.add(file)
    else:
        if file.content != content:
            _snapshot_old_content(db, project_id, safe_path, file.content)
        file.content = content
    db.commit()
    db.refresh(file)
    return file, created


def rename_file(db: Session, project_id, path: str, new_path: str) -> ProjectFile:
    safe_old = validate_path(path)
    safe_new = validate_path(new_path)
    if safe_old == safe_new:
        return _get_file(db, project_id, safe_old)
    exists = db.scalar(
        select(ProjectFile.id).where(
            ProjectFile.project_id == project_id, ProjectFile.path == safe_new
        )
    )
    if exists is not None:
        raise FileError(f"目标路径已存在：{safe_new}", status=409)
    file = _get_file(db, project_id, safe_old)
    file.path = safe_new
    # 历史快照跟随文件移动
    db.execute(
        update(CodeSnapshot)
        .where(CodeSnapshot.project_id == project_id, CodeSnapshot.path == safe_old)
        .values(path=safe_new)
    )
    db.commit()
    db.refresh(file)
    return file


def delete_file(db: Session, project_id, path: str) -> None:
    file = _get_file(db, project_id, validate_path(path))
    # 文件删除时一并清理其历史快照，避免孤儿数据与语义歧义（见 DECISIONS D15）。
    db.execute(
        delete(CodeSnapshot).where(
            CodeSnapshot.project_id == project_id,
            CodeSnapshot.path == file.path,
        )
    )
    db.delete(file)
    db.commit()


def _is_cpp_project(project: Project) -> bool:
    """按技术栈声明判定 C++ 项目（C++/CPP 大小写不敏感）。"""
    return any(s.strip().lower() in ("c++", "cpp") for s in (project.stack or []))


CPP_MAIN = """#include <iostream>
#include "math.hpp"

// C++ 项目入口：点击行号左侧设置断点，再点工具栏「调试」启动 LLDB 会话。
// 调试暂停后，右侧「调试」面板与教学画布会显示真实的变量、地址与指针关系。

int fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int main() {
    int a = 10;
    int b = 20;
    int sum = add(a, b);

    int* p = &a;        // 指向栈变量：调试画布会画出已验证的 p -> a
    int* np = nullptr;  // 空指针：显式状态，不画箭头
    int* heap = new int(42);  // 堆指针：地址未解析（不虚构指向）
    *p = 30;            // 通过指针修改 a —— 单步后观察 a 与 *p 的变化

    int f = fib(4);     // 递归：调用栈面板可见多个 fib 帧
    std::cout << "sum=" << sum << " a=" << a << " *heap=" << *heap
              << " fib(4)=" << f << std::endl;
    delete heap;
    return 0;
}
"""

CPP_MATH_HPP = """#pragma once

// 多翻译单元示例：math.cpp 提供实现，main.cpp 引用此头文件。
// 运行/调试时系统会把所有 .cpp 一起编译链接为真实可执行程序。
int add(int a, int b);
int mul(int a, int b);
"""

CPP_MATH_CPP = """#include "math.hpp"

int add(int a, int b) {
    return a + b;
}

int mul(int a, int b) {
    return a * b;
}
"""

CPP_TEST = """#include <cstdio>
#include "../src/math.hpp"

// C++ 测试约定：每个测试文件编译为独立可执行程序。
// 通过 = 退出码 0 且有输出；断言失败用返回码报告。
// 运行方式：测试面板「运行测试」，或在此文件上点「测试」按钮。

int main() {
    if (add(2, 3) != 5) { printf("add(2,3) != 5 FAIL"); return 1; }
    printf("add(2,3) = %d ... ok", add(2, 3));
    if (mul(3, 4) != 12) { printf("mul(3,4) != 12 FAIL"); return 1; }
    printf("mul(3,4) = %d ... ok", mul(3, 4));
    return 0;
}
"""


def starter_files_for(project: Project) -> list[ProjectFile]:
    """新项目的初始脚手架（确定性模板，非 AI 生成）。

    按技术栈分支：C++ 项目种子 C++ 多文件脚手架（可运行/可测试/可调试，
    含指针演示）；其余维持 TypeScript 脚手架。
    后续接入 Curriculum Engine 后将由课程的 starterState 接管。
    """
    readme = (
        f"# {project.title}\n\n"
        f"{project.description or '项目说明待补充。'}\n\n"
        "> 这是 ProjectWeave 创建的初始文件，可以自由修改或删除。\n"
    )
    main_ts = (
        "// 项目入口草稿：在左侧文件树中组织你的代码。\n"
        "// 当前支持编辑、保存、运行与测试（浏览器沙箱）；更多能力将逐步接入。\n\n"
        "export function greet(name: string): string {\n"
        '  return `Hello, ${name}!`;\n'
        "}\n"
    )
    # 浏览器运行器为单文件模式（Worker 中无法解析 import），示例测试自包含。
    main_test_ts = (
        "// 示例测试：*.test.ts / *.test.js 会出现在测试面板，可整体运行。\n"
        "// 断言库：describe / it / test / expect（toBe、toEqual、toContain、toThrow、.not…）。\n"
        "// 注意：浏览器运行器为单文件模式，暂不支持 import；请把被测逻辑写在测试文件内或复制过来。\n\n"
        "function add(a: number, b: number): number {\n"
        "  return a + b;\n"
        "}\n\n"
        "describe('示例 · add', () => {\n"
        "  it('返回两数之和', () => {\n"
        "    expect(add(1, 2)).toBe(3);\n"
        "  });\n\n"
        "  it('对负数同样生效', () => {\n"
        "    expect(add(-1, -2)).toBe(-3);\n"
        "  });\n"
        "});\n"
    )
    cpp_readme_suffix = (
        "\n## 起步\n\n"
        "- **运行**：打开 `src/main.cpp` 点「▶ 运行」（远程沙箱 Clang 19 / C++20，多文件一起编译链接）\n"
        "- **测试**：打开 `tests/test_math.cpp` 点「▶ 测试」，或测试面板整体运行\n"
        "- **调试**：在 `src/main.cpp` 行号左侧点一下设断点 → 工具栏「调试」→ 暂停后看"
        "「调试」面板（调用栈/变量）与教学画布（内存与指针图）\n"
        if _is_cpp_project(project)
        else ""
    )
    if _is_cpp_project(project):
        readme = readme + cpp_readme_suffix
        return [
            ProjectFile(project_id=project.id, path="README.md", content=readme),
            ProjectFile(project_id=project.id, path="src/main.cpp", content=CPP_MAIN),
            ProjectFile(project_id=project.id, path="src/math.hpp", content=CPP_MATH_HPP),
            ProjectFile(project_id=project.id, path="src/math.cpp", content=CPP_MATH_CPP),
            ProjectFile(project_id=project.id, path="tests/test_math.cpp", content=CPP_TEST),
        ]
    return [
        ProjectFile(project_id=project.id, path="README.md", content=readme),
        ProjectFile(project_id=project.id, path="src/main.ts", content=main_ts),
        ProjectFile(project_id=project.id, path="src/main.test.ts", content=main_test_ts),
    ]


# ---------------------------------------------------------------------------
# 快照历史与 codeVersion
# ---------------------------------------------------------------------------


class SnapshotNotFoundError(FileError):
    def __init__(self, snapshot_id) -> None:
        super().__init__(f"snapshot not found: {snapshot_id}", status=404)


def list_snapshots(db: Session, project_id, path: str) -> list[CodeSnapshot]:
    safe_path = validate_path(path)
    stmt = (
        select(CodeSnapshot)
        .where(CodeSnapshot.project_id == project_id, CodeSnapshot.path == safe_path)
        .order_by(CodeSnapshot.created_at.desc(), CodeSnapshot.id.desc())
    )
    return list(db.scalars(stmt))


def get_snapshot(db: Session, project_id, snapshot_id) -> CodeSnapshot:
    snapshot = db.get(CodeSnapshot, snapshot_id)
    if snapshot is None or snapshot.project_id != project_id:
        raise SnapshotNotFoundError(snapshot_id)
    return snapshot


def restore_snapshot(db: Session, project_id, snapshot_id) -> ProjectFile:
    """把快照内容写回工作区文件。

    当前内容若与快照不同，会先进入快照历史——任何路径都不丢数据。
    """
    snapshot = get_snapshot(db, project_id, snapshot_id)
    file = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id, ProjectFile.path == snapshot.path
        )
    )
    if file is None:
        file = ProjectFile(project_id=project_id, path=snapshot.path, content=snapshot.content)
        db.add(file)
    elif file.content != snapshot.content:
        _snapshot_old_content(db, project_id, snapshot.path, file.content)
        file.content = snapshot.content
    db.commit()
    db.refresh(file)
    return file


def compute_code_version(db: Session, project_id) -> dict:
    """项目当前代码状态的内容指纹（设计文档 14.3 的 codeVersion）。

    对全部文件按路径排序后拼接 `path\\0sha256(content)\\n` 再整体哈希；
    只反映 project_files 当前态，与快照历史无关。
    """
    files = list_files(db, project_id)
    digest = hashlib.sha256()
    for file in files:  # list_files 已按 path 排序
        digest.update(file.path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(file.content.encode("utf-8"))
        digest.update(b"\n")
    return {
        "codeVersion": f"sha256:{digest.hexdigest()}",
        "fileCount": len(files),
    }
