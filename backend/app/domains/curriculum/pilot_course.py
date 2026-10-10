"""试点课程：TypeScript Markdown 解析器（P4.1）。

三个任务由简到繁：标题识别 → 行内语法 → 组合模块。
每个任务包含说明、前置知识、初始代码、验收用例与边界条件测试；
全部兼容浏览器 Worker 单文件 JS/TS 执行（无 import、自包含）。

确定性内容，非 AI 生成（同 D17/D18 原则）。
"""

PILOT_COURSE_TASKS: list[dict] = [
    {
        "taskId": "md-heading",
        "milestone": 1,
        "title": "识别 Markdown 标题",
        "description": (
            "编写函数 parseHeadings(text: string): string[]，"
            "输入 Markdown 文本，返回所有标题行的纯文本内容。"
            "标题以 # 开头（# 到 ######），# 后必须有空格。"
            "返回结果去掉 # 前缀并去除首尾空格。"
        ),
        "dependsOn": [],
        "requiredConcepts": ["js.strings", "js.control-flow"],
        "deliverable": "parseHeadings 函数通过全部测试用例",
        "effortBand": "small",
        "acceptanceCriteria": [
            "识别 1-6 级标题（# 到 ######）并去掉 # 前缀",
            "# 后必须有空格才算标题（#tag 不是标题）",
            "非标题行不出现在结果中",
            "空输入返回空数组",
        ],
        "starterFiles": [
            {
                "path": "src/parser/headings.ts",
                "content": (
                    "/**\n"
                    " * 任务：识别 Markdown 标题\n"
                    " * 编写 parseHeadings(text)，返回所有标题行的纯文本（去掉 # 前缀）。\n"
                    " *\n"
                    " * 提示：\n"
                    " * - 标题以 # 开头，# 后必须有空格\n"
                    " * - 支持 # 到 ######（6 级）\n"
                    " * - 返回时去掉 # 前缀并去除首尾空格\n"
                    " */\n"
                    "export function parseHeadings(text: string): string[] {\n"
                    "  // TODO: 实现这个函数\n"
                    "  return [];\n"
                    "}\n"
                ),
            },
        ],
        "testFiles": ["src/parser/headings.test.ts"],
    },
    {
        "taskId": "md-inline",
        "milestone": 2,
        "title": "解析粗体与斜体",
        "description": (
            "编写函数 parseInline(text: string): string，"
            "将 Markdown 行内语法转为纯文本：**bold** 去掉星号保留内容，"
            "*italic* 同理。嵌套不要求处理（如 **bo*ld*** 可忽略）。"
        ),
        "dependsOn": ["md-heading"],
        "requiredConcepts": ["js.strings"],
        "deliverable": "parseInline 函数通过全部测试用例",
        "effortBand": "medium",
        "acceptanceCriteria": [
            "**bold** 转为 bold",
            "*italic* 转为 italic",
            "无标记的文本原样返回",
            "单个星号（不成对）不转换",
        ],
        "starterFiles": [
            {
                "path": "src/parser/inline.ts",
                "content": (
                    "/**\n"
                    " * 任务：解析粗体与斜体\n"
                    " * 编写 parseInline(text)，将 **bold** 和 *italic* 转为纯文本。\n"
                    " *\n"
                    " * 提示：\n"
                    " * - **内容** → 内容（去掉四个星号）\n"
                    " * - *内容* → 内容（去掉两个星号）\n"
                    " * - 不成对的星号不处理\n"
                    " */\n"
                    "export function parseInline(text: string): string {\n"
                    "  // TODO: 实现这个函数\n"
                    "  return text;\n"
                    "}\n"
                ),
            },
        ],
        "testFiles": ["src/parser/inline.test.ts"],
    },
    {
        "taskId": "md-module",
        "milestone": 3,
        "title": "组合为可复用转换模块",
        "description": (
            "编写函数 transformMarkdown(text: string): string，"
            "组合 parseHeadings 与 parseInline 的逻辑："
            "标题行只保留纯文本标题（加大写/不变均可），"
            "非标题行应用行内转换，最终用 \\n 连接返回。"
            "将三个函数放入同一文件作为可复用模块。"
        ),
        "dependsOn": ["md-inline"],
        "requiredConcepts": ["js.functions", "eng.modules"],
        "deliverable": "transformMarkdown 函数通过全部测试用例",
        "effortBand": "medium",
        "acceptanceCriteria": [
            "标题行转为纯文本标题",
            "非标题行应用行内语法转换",
            "空输入返回空字符串",
            "结果用换行符连接",
        ],
        "starterFiles": [
            {
                "path": "src/parser/transform.ts",
                "content": (
                    "/**\n"
                    " * 任务：组合为可复用转换模块\n"
                    " * 编写 transformMarkdown(text)，组合标题与行内解析。\n"
                    " *\n"
                    " * 要求：\n"
                    " * - 标题行只保留纯文本标题\n"
                    " * - 非标题行应用行内转换（去掉 ** 和 *）\n"
                    " * - 结果用 \\n 连接\n"
                    " */\n"
                    "export function parseHeadings(text: string): string[] {\n"
                    "  // 复制你上一个任务的实现\n"
                    "  return [];\n"
                    "}\n\n"
                    "export function parseInline(text: string): string {\n"
                    "  // 复制你上一个任务的实现\n"
                    "  return text;\n"
                    "}\n\n"
                    "export function transformMarkdown(text: string): string {\n"
                    "  // TODO: 组合以上两个函数\n"
                    "  return '';\n"
                    "}\n"
                ),
            },
        ],
        "testFiles": ["src/parser/transform.test.ts"],
    },
]

PILOT_TEST_FILE_CONTENTS: dict[str, str] = {
    "src/parser/headings.test.ts": (
        "// 任务测试：识别 Markdown 标题\n"
        "// 浏览器 Worker 单文件执行；被测函数写在同文件内（不支持 import）。\n\n"
        "function parseHeadings(text: string): string[] {\n"
        "  // === 把 src/parser/headings.ts 的实现复制到这里 ===\n"
        "  return [];\n"
        "}\n\n"
        "describe('parseHeadings', () => {\n"
        "  it('识别 1-6 级标题', () => {\n"
        "    expect(parseHeadings('# 一级')).toEqual(['一级']);\n"
        "    expect(parseHeadings('## 二级')).toEqual(['二级']);\n"
        "    expect(parseHeadings('###### 六级')).toEqual(['六级']);\n"
        "  });\n\n"
        "  it('# 后必须有空格', () => {\n"
        "    expect(parseHeadings('#tag 不是标题')).toEqual([]);\n"
        "    expect(parseHeadings('##tag 也不是')).toEqual([]);\n"
        "  });\n\n"
        "  it('非标题行不出现在结果中', () => {\n"
        "    expect(parseHeadings('普通文本')).toEqual([]);\n"
        "    expect(parseHeadings('  # 缩进的不是标题')).toEqual([]);\n"
        "  });\n\n"
        "  it('多行混合', () => {\n"
        "    const text = '# 标题一\\n正文\\n## 标题二\\n# 无空格#tag\\n### 三级';\n"
        "    expect(parseHeadings(text)).toEqual(['标题一', '标题二', '三级']);\n"
        "  });\n\n"
        "  it('空输入返回空数组', () => {\n"
        "    expect(parseHeadings('')).toEqual([]);\n"
        "  });\n"
        "});\n"
    ),
    "src/parser/inline.test.ts": (
        "// 任务测试：解析粗体与斜体\n\n"
        "function parseInline(text: string): string {\n"
        "  // === 把 src/parser/inline.ts 的实现复制到这里 ===\n"
        "  return text;\n"
        "}\n\n"
        "describe('parseInline', () => {\n"
        "  it('粗体转纯文本', () => {\n"
        "    expect(parseInline('**重要**')).toBe('重要');\n"
        "    expect(parseInline('**a** 和 **b**')).toBe('a 和 b');\n"
        "  });\n\n"
        "  it('斜体转纯文本', () => {\n"
        "    expect(parseInline('*轻*')).toBe('轻');\n"
        "  });\n\n"
        "  it('无标记原样返回', () => {\n"
        "    expect(parseInline('普通文本')).toBe('普通文本');\n"
        "  });\n\n"
        "  it('单个星号不转换', () => {\n"
        "    expect(parseInline('2 * 3 = 6')).toBe('2 * 3 = 6');\n"
        "  });\n"
        "});\n"
    ),
    "src/parser/transform.test.ts": (
        "// 任务测试：组合为可复用转换模块\n\n"
        "function parseHeadings(text: string): string[] {\n"
        "  // 复制实现\n"
        "  return [];\n"
        "}\n\n"
        "function parseInline(text: string): string {\n"
        "  // 复制实现\n"
        "  return text;\n"
        "}\n\n"
        "function transformMarkdown(text: string): string {\n"
        "  // 复制实现\n"
        "  return '';\n"
        "}\n\n"
        "describe('transformMarkdown', () => {\n"
        "  it('标题行转为纯文本标题', () => {\n"
        "    expect(transformMarkdown('# 标题')).toBe('标题');\n"
        "  });\n\n"
        "  it('非标题行应用行内转换', () =>{\n"
        "    expect(transformMarkdown('**粗体** 正文')).toBe('粗体 正文');\n"
        "  });\n\n"
        "  it('多行混合', () => {\n"
        "    const result = transformMarkdown('# T\\n**b**\\nplain');\n"
        "    expect(result).toBe('T\\nb\\nplain');\n"
        "  });\n\n"
        "  it('空输入返回空字符串', () => {\n"
        "    expect(transformMarkdown('')).toBe('');\n"
        "  });\n"
        "});\n"
    ),
}
