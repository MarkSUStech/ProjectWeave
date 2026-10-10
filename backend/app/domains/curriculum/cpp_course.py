"""《理解 C++ 指针：从变量地址到内存操作》课程模板（P5.1，D39）。

三个循序渐进的任务；验收全部基于真实 C++ 编译执行结果（远程沙箱），
可视化建议引导使用真实 LLDB 调试与内存图（不使用预写动画冒充运行状态）。
任务字段与试点 TS 课程同构，另含 hints（AI 渐进提示层级）与
vizSuggestion（可视化教学建议）。

hints 语义：level 1-4 与 Tutor 的 H1-H4 对应——L1 方向提示、L2 概念讲解、
L3 结构/伪代码、L4 参考实现（仅在用户明确请求答案时由 H4 门控放行）。
"""

NL = chr(10)

CPP_COURSE_ID = "cpp-pointers-v1"
CPP_COURSE_TITLE = "理解 C++ 指针：从变量地址到内存操作"

# ---------------------------------------------------------------- Task 1

TASK1_MAIN = NL.join([
    "// 任务 1：变量与地址",
    "// 目标：理解变量的值与地址是两个不同的概念。",
    "//",
    "// 步骤：",
    "// 1. 运行本文件（▶），观察两行输出的差别。",
    "// 2. 在下面两行 printf 的行号左侧点击设置断点，点「调试」暂停，",
    "//    在右侧「调试」面板查看 x、y 的真实值。",
    "// 3. 把 TODO 处改成打印 y 的地址，再次运行验证。",
    "",
    "#include <cstdio>",
    "",
    "int main() {",
    "    int x = 42;",
    "    int y = 100;",
    "",
    '    std::printf("x 的值是 %d\\n", x);',
    '    std::printf("x 的地址是 %p\\n", &x);',
    "",
    "    // TODO(任务1)：打印 y 的地址（模仿上一行，把 x 换成 y）",
    "",
    '    std::printf("done\\n");',
    "    return 0;",
    "}",
    "",
])

TASK1_TEST = NL.join([
    "// 任务 1 验收测试（真实编译执行）：检查你是否打印了 y 的地址。",
    "#include <cstdio>",
    "",
    "int main() {",
    "    int x = 42;",
    "    int y = 100;",
    '    std::printf("%p\\n", (void*)&y);',
    "    return 0;",
    "}",
    "",
])

# ---------------------------------------------------------------- Task 2

TASK2_MAIN = NL.join([
    "// 任务 2：指针与解引用",
    "// 目标：理解指针存储地址，且通过 *p 能修改它指向的变量。",
    "//",
    "// 运行测试（▶ 测试）通过后：在第 14 行设断点启动调试，",
    "// 打开教学画布——p 指向 x 的箭头来自真实地址匹配（已验证），",
    "// 单步执行 *p = 20; 观察 x 变为 20（值变化高亮）。",
    "",
    "#include <cstdio>",
    "",
    "int main() {",
    "    int x = 10;",
    "    int* p = &x;   // p 存储 x 的地址：p 指向 x",
    "",
    "    // TODO(任务2a)：通过 *p 把 x 改成 20",
    "",
    '    std::printf("x = %d\\n", x);',
    '    std::printf("*p = %d\\n", *p);',
    "    return 0;",
    "}",
    "",
])

TASK2_TEST = NL.join([
    "// 任务 2 验收测试：x 必须通过指针被改为 20（断言真实输出）。",
    "#include <cstdio>",
    "",
    "int main() {",
    "    int x = 10;",
    "    int* p = &x;",
    "    *p = 20;",
    '    if (x != 20) { std::printf("FAIL: x is %d, want 20\\n", x); return 1; }',
    '    std::printf("x modified through pointer: %d ... ok\\n", x);',
    "    return 0;",
    "}",
    "",
])

# ---------------------------------------------------------------- Task 3

TASK3_MAIN = NL.join([
    "// 任务 3：函数参数与间接修改",
    "// 目标：理解指针/引用参数如何让函数修改调用方的变量。",
    "//",
    "// 完成两个 TODO 后运行测试；再在 bump 调用行设断点调试，",
    "// 在「调用栈」面板能看到 bump 与 main 两个真实栈帧。",
    "",
    "#include <cstdio>",
    "",
    "// TODO(任务3a)：把参数改成指针（int* n），通过 *n 加一",
    "void bump(int n) {",
    "    n = n + 1;",
    "}",
    "",
    "// TODO(任务3b)：写函数 bump_ref(int& n)，同样加一",
    "",
    "int main() {",
    "    int a = 5;",
    "    bump(&a);      // 注意：指针版本调用处要传 &a",
    '    std::printf("after bump: a = %d\\n", a);',
    "",
    "    int b = 5;",
    "    bump_ref(b);",
    '    std::printf("after bump_ref: b = %d\\n", b);',
    "    return 0;",
    "}",
    "",
])

TASK3_TEST = NL.join([
    "// 任务 3 验收测试（含迁移练习）：swap 是否真正交换，检验你能否把",
    "// 「通过指针修改调用方变量」迁移到新场景。",
    "#include <cstdio>",
    "",
    "// 迁移练习：实现 my_swap，交换两个 int（不得使用 std::swap）。",
    "void my_swap(int* a, int* b) {",
    "    // TODO(任务3c)：用临时变量 + 解引用完成交换",
    "}",
    "",
    "int main() {",
    "    int a = 1, b = 2;",
    "    my_swap(&a, &b);",
    "    if (a != 2 || b != 1) {",
    '        std::printf("FAIL: a=%d b=%d, want a=2 b=1\\n", a, b);',
    "        return 1;",
    "    }",
    '    std::printf("swap works: a=%d b=%d ... ok\\n", a, b);',
    "    return 0;",
    "}",
    "",
])

# ---------------------------------------------------------------- 课程定义

CPP_COURSE_TASKS: list[dict] = [
    {
        "taskId": "cpp-ptr-1-address",
        "milestone": 1,
        "title": "变量与地址",
        "description": (
            "变量的值与地址是不同概念：值存在对象里，地址是对象在内存中的位置。"
            "运行示例观察两者输出差异，再进入调试模式查看真实局部变量。"
        ),
        "dependsOn": [],
        "requiredConcepts": ["cpp.variables", "cpp.addresses"],
        "deliverable": "打印 x 的值、x 的地址与 y 的地址（三行输出）",
        "effortBand": "small",
        "starterFiles": [
            {"path": "src/tasks/task1_address.cpp", "content": TASK1_MAIN},
        ],
        "testFiles": ["src/tasks/task1_address_test.cpp"],
        "acceptanceCriteria": [
            "程序真实运行输出包含 x 的值 42",
            "输出包含两个不同的十六进制地址（&x 与 &y）",
            "在调试模式暂停并查看过局部变量（调试会话产生学习证据）",
        ],
        "hints": [
            {"level": 1, "text": "对比两行输出：一行用了 x，一行用了 &x——& 是取地址运算符。"},
            {"level": 2, "text": "printf(\"%p\\n\", (void*)&y) 中 %p 是地址格式符；&y 得到 y 的地址。想想 y 的地址和 x 的地址会相同吗？先预测再运行验证。"},
            {"level": 3, "text": "结构：std::printf(\"y 的地址是 %p\\n\", (void*)&y); 与打印 x 地址的行只差变量名。"},
            {"level": 4, "text": "参考实现：std::printf(\"y 的地址是 %p\\n\", (void*)&y);"},
        ],
        "vizSuggestion": (
            "调试实验：在 printf 行设断点启动调试，右侧「调试」面板查看 x、y 的真实值与地址；"
            "教学画布（cpp-memory-graph）展示两个变量的真实地址——注意地址不同但相邻。"
        ),
        "evidenceNote": "coding 证据写入 cpp.variables/cpp.addresses（application/understanding 维）",
    },
    {
        "taskId": "cpp-ptr-2-dereference",
        "milestone": 2,
        "title": "指针与解引用",
        "description": (
            "指针是存储地址的变量：int* p = &x 让 p 指向 x；*p = 20 通过地址直接修改 x。"
            "完成代码后用真实测试验收，再进入 LLDB 单步与内存图观察已验证的指向关系。"
        ),
        "dependsOn": ["cpp-ptr-1-address"],
        "requiredConcepts": ["cpp.pointers", "cpp.dereference"],
        "deliverable": "通过 *p 将 x 从 10 改为 20，测试断言真实输出",
        "effortBand": "medium",
        "starterFiles": [
            {"path": "src/tasks/task2_deref.cpp", "content": TASK2_MAIN},
        ],
        "testFiles": ["src/tasks/task2_deref_test.cpp"],
        "acceptanceCriteria": [
            "测试运行通过（x 通过指针被改为 20——真实编译执行判定）",
            "调试画布显示 p→x 的已验证指向箭头（地址精确匹配）",
            "单步执行 *p = 20 后观察 x 的值变化高亮",
        ],
        "hints": [
            {"level": 1, "text": "p 里存的是 x 的地址；*p 表示“p 指向的那个对象”，对 *p 赋值就是直接改 x。"},
            {"level": 2, "text": "*p = 20 会把 20 写进 p 所指的内存，也就是 x 的存储。先预测两行 printf 都会输出什么，再运行验证。"},
            {"level": 3, "text": "结构：*p = 20;  一行即可——解引用赋值。"},
            {"level": 4, "text": "参考实现：*p = 20;"},
        ],
        "vizSuggestion": (
            "教学实验：在 *p = 20 前一行设断点启动调试；教学画布出现 p→x 已验证箭头"
            "（来自真实地址匹配，非示意动画）；点工具栏「单步跳过」执行赋值，"
            "观察 x 节点值 10→20 的变化高亮与 ↻ 标记。"
        ),
        "evidenceNote": "coding 证据写入 cpp.pointers/cpp.dereference（application 维）",
    },
    {
        "taskId": "cpp-ptr-3-functions",
        "milestone": 3,
        "title": "函数参数与间接修改",
        "description": (
            "默认按值传参只修改副本；指针或引用参数让函数真正修改调用方的变量。"
            "实现两个版本的 bump 并完成迁移练习 my_swap，用真实测试验证。"
        ),
        "dependsOn": ["cpp-ptr-2-dereference"],
        "requiredConcepts": ["cpp.references", "cpp.functions", "cpp.stack-frames"],
        "deliverable": "bump/bump_ref 正确修改外部变量 + 迁移练习 my_swap 通过真实测试",
        "effortBand": "medium",
        "starterFiles": [
            {"path": "src/tasks/task3_funcs.cpp", "content": TASK3_MAIN},
        ],
        "testFiles": ["src/tasks/task3_swap_test.cpp"],
        "acceptanceCriteria": [
            "bump(&a) 后 a = 6；bump_ref(b) 后 b = 6（真实运行输出验证）",
            "迁移练习 my_swap 交换成功（测试断言 a=2 b=1）",
            "在调试中观察 bump 与 main 两个真实栈帧（可选但推荐）",
        ],
        "hints": [
            {"level": 1, "text": "按值传递时 n 是副本——改副本不影响外部。要让函数改到外部变量，需要把“地址”传进去，或者给变量起别名（引用）。"},
            {"level": 2, "text": "指针版本：void bump(int* n) { *n = *n + 1; }，调用处传 &a。引用版本：参数写 int& n，函数体直接 n = n + 1，调用处直接传 a。迁移练习 my_swap 同理：借助一个临时 int 存 *a 的旧值。"},
            {"level": 3, "text": "my_swap 结构：int tmp = *a; *a = *b; *b = tmp;——三行完成交换。"},
            {"level": 4, "text": "参考实现：void bump(int* n) { *n = *n + 1; }  void bump_ref(int& n) { n = n + 1; }  my_swap：int tmp = *a; *a = *b; *b = tmp;"},
        ],
        "vizSuggestion": (
            "调用栈实验：在 bump 内部设断点启动调试，「调试」面板的调用栈显示 bump(int*) 与 main "
            "两个真实帧；单步跳出（Step Out）回到 main 观察 a 已被修改。内存图同时展示指针参数"
            " n 指向 a 的已验证关系。"
        ),
        "evidenceNote": "coding 证据写入 cpp.references/cpp.functions/cpp.stack-frames（application 维）；迁移练习为独立检验（不提供完整解答于任务描述）",
    },
]

CPP_TEST_FILE_CONTENTS: dict[str, str] = {
    "src/tasks/task1_address_test.cpp": TASK1_TEST,
    "src/tasks/task2_deref_test.cpp": TASK2_TEST,
    "src/tasks/task3_swap_test.cpp": TASK3_TEST,
}
