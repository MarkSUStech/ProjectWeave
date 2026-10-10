"""样板课程（TS/React Markdown 编辑器）的任务模板。

确定性内容，映射设计文档 §2.2 的六个里程碑与附录 B 的任务-知识表；
任意目标的自动任务生成属于后续版本（界面已标注）。
"""

SAMPLE_COURSE_TASKS: list[dict] = [
    {
        "taskId": "task-scaffold",
        "milestone": 1,
        "title": "建立页面骨架",
        "description": "搭建编辑器布局：编辑区与预览区并排。",
        "dependsOn": [],
        "requiredConcepts": ["browser.dom"],
        "deliverable": "可打开的编辑器布局页面",
        "effortBand": "small",
    },
    {
        "taskId": "task-input",
        "milestone": 2,
        "title": "编辑文本",
        "description": "输入事件驱动内容更新，理解状态与 DOM 的区别。",
        "dependsOn": ["task-scaffold"],
        "requiredConcepts": ["js.objects", "js.callbacks-events"],
        "deliverable": "可输入与编辑文本的编辑区",
        "effortBand": "medium",
    },
    {
        "taskId": "task-preview",
        "milestone": 3,
        "title": "实时预览",
        "description": "文本处理与 Markdown 基础渲染，输入同步更新预览。",
        "dependsOn": ["task-input"],
        "requiredConcepts": ["js.strings", "js.functions"],
        "deliverable": "与输入同步的 Markdown 预览",
        "effortBand": "medium",
    },
    {
        "taskId": "task-persistence",
        "milestone": 4,
        "title": "本地保存",
        "description": "浏览器存储与初始化，刷新后内容恢复。",
        "dependsOn": ["task-preview"],
        "requiredConcepts": ["browser.storage"],
        "deliverable": "刷新后笔记内容恢复",
        "effortBand": "medium",
    },
    {
        "taskId": "task-search",
        "milestone": 5,
        "title": "基础搜索",
        "description": "字符串匹配与过滤，处理空关键词等边界条件。",
        "dependsOn": ["task-persistence"],
        "requiredConcepts": ["js.arrays", "eng.errors"],
        "deliverable": "关键词搜索功能",
        "effortBand": "medium",
    },
    {
        "taskId": "task-delivery",
        "milestone": 6,
        "title": "完整交付",
        "description": "为关键函数编写测试，模块拆分与错误处理收尾。",
        "dependsOn": ["task-search"],
        "requiredConcepts": ["eng.testing", "eng.modules", "ts.annotations"],
        "deliverable": "带测试的可交付版本",
        "effortBand": "large",
    },
]
