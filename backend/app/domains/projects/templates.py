"""项目模板注册表（P5.1，D39）：按技术栈选择初始脚手架与课程。

- 显式、版本化：每个模板有稳定 id + version；项目创建时记录所选模板
  （projects.template_id），后续课程种子/规划按模板解析，不靠文件扩展名
  猜测项目语言身份。
- 课程与脚手架解耦：starter_files 只在项目创建时写入一次；课程文件由
  curriculum 域按 course_id 种子（且只在路径不存在时写入——重规划绝不
  覆盖用户代码）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectTemplate:
    template_id: str          # 如 "cpp-pointers-v1"
    version: int
    display_name: str
    stack_keywords: tuple[str, ...]  # 命中即选（大小写不敏感）
    course_id: str | None     # 对应课程模板（curriculum 域）；None = 暂无课程
    language: str             # 主语言标识（执行层 LanguageProfile id）


# ---------------------------------------------------------------- C++ 脚手架

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

# ---------------------------------------------------------------- Python 脚手架

PY_MAIN = """# 项目入口：点工具栏「▶ 运行」在远程沙箱（CPython 3.12）执行；
# 终端面板的 stdin 输入框可给 input() 提供输入。


def greet(name: str) -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    who = input() or "ProjectWeave"
    print(greet(who))
"""

PY_TEST = """# Python 测试约定：test_*.py / *_test.py 在远程沙箱以 pytest 运行。
from main import greet


def test_greet():
    assert greet("Ada") == "Hello, Ada!"


def test_greet_empty():
    assert greet("") == "Hello, !"
"""

# ---------------------------------------------------------------- 模板注册表

TEMPLATES: tuple[ProjectTemplate, ...] = (
    ProjectTemplate(
        template_id="cpp-pointers-v1",
        version=1,
        display_name="C++20 指针与内存",
        stack_keywords=("c++", "cpp", "clang"),
        course_id="cpp-pointers-v1",
        language="cpp",
    ),
    ProjectTemplate(
        template_id="python-starter-v1",
        version=1,
        display_name="Python 起步",
        stack_keywords=("python", "cpython", "django", "flask", "fastapi"),
        course_id=None,  # Python 课程待制作：学习路线如实为空，不展示其他语言课程
        language="python",
    ),
    ProjectTemplate(
        template_id="ts-markdown-v1",
        version=1,
        display_name="TypeScript Markdown 编辑器",
        stack_keywords=(),  # 兜底默认（未命中其他模板时）
        course_id="ts-markdown-v1",
        language="typescript",
    ),
)

_BY_ID = {t.template_id: t for t in TEMPLATES}
DEFAULT_TEMPLATE = _BY_ID["ts-markdown-v1"]


def resolve_template(stack: list[str] | None) -> ProjectTemplate:
    """按技术栈声明选择模板（首个命中；默认 TS）。"""
    for item in stack or []:
        key = item.strip().lower()
        for template in TEMPLATES:
            if key in template.stack_keywords:
                return template
    return DEFAULT_TEMPLATE


def get_template(template_id: str | None) -> ProjectTemplate | None:
    return _BY_ID.get(template_id or "")


def starter_files_for(template: ProjectTemplate, project_id, readme: str):
    """按模板生成初始文件（确定性内容）；返回 (path, content) 列表。"""
    if template.template_id == "cpp-pointers-v1":
        readme = (
            readme
            + "\n## 起步\n\n"
            + "- **运行**：打开 `src/main.cpp` 点「▶ 运行」（远程沙箱 Clang 19 / C++20，多文件一起编译链接）\n"
            + "- **测试**：打开 `tests/test_math.cpp` 点「▶ 测试」，或测试面板整体运行\n"
            + "- **调试**：在 `src/main.cpp` 行号左侧点一下设断点 → 工具栏「调试」→ 暂停后看"
            "「调试」面板（调用栈/变量）与教学画布（内存与指针图）\n"
        )
        return [
            ("README.md", readme),
            ("src/main.cpp", CPP_MAIN),
            ("src/math.hpp", CPP_MATH_HPP),
            ("src/math.cpp", CPP_MATH_CPP),
            ("tests/test_math.cpp", CPP_TEST),
        ]
    if template.template_id == "python-starter-v1":
        readme = (
            readme
            + "\n## 起步\n\n"
            + "- **运行**：打开 `src/main.py` 点「▶ 运行」（远程沙箱 CPython 3.12）\n"
            + "- **测试**：`tests/test_main.py` 以 pytest 运行\n"
            + "- 说明：Python 课程内容制作中——学习路线暂为空，可自由编码。\n"
        )
        return [
            ("README.md", readme),
            ("src/main.py", PY_MAIN),
            ("tests/test_main.py", PY_TEST),
        ]
    # 默认 TypeScript 脚手架（与 P1 起的初始内容一致）
    NL = chr(10)
    main_ts = NL.join([
        "// 项目入口草稿：在左侧文件树中组织你的代码。",
        "// 当前支持编辑、保存、运行与测试（浏览器沙箱）；更多能力将逐步接入。",
        "",
        "export function greet(name: string): string {",
        "  return `Hello, ${name}!`;",
        "}",
        "",
    ])
    main_test_ts = NL.join([
        "// 示例测试：*.test.ts / *.test.js 会出现在测试面板，可整体运行。",
        "// 断言库：describe / it / test / expect（toBe、toEqual、toContain、toThrow、.not…）。",
        "// 注意：浏览器运行器为单文件模式，暂不支持 import；请把被测逻辑写在测试文件内或复制过来。",
        "",
        "function add(a: number, b: number): number {",
        "  return a + b;",
        "}",
        "",
        "describe('示例 · add', () => {",
        "  it('返回两数之和', () => {",
        "    expect(add(1, 2)).toBe(3);",
        "  });",
        "",
        "  it('对负数同样生效', () => {",
        "    expect(add(-1, -2)).toBe(-3);",
        "  });",
        "});",
        "",
    ])
    return [
        ("README.md", readme),
        ("src/main.ts", main_ts),
        ("src/main.test.ts", main_test_ts),
    ]
