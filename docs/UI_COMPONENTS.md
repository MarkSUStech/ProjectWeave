# ProjectWeave 前端开源组件与设计系统

核验日期：2026-10-10。范围：现有项目工作台、知识图谱和教学 IDE 的增量重建。
业务仍使用原 REST API、文件/快照 hook、Worker 运行器、学习证据及 Tutor Policy Gate；没有新增业务 mock 分支。

## 已集成组件

版本取自安装后的 package-lock.json 与包内 package.json；复制型组件采用上游源码快照，不声明 npm 包版本。
下表中的“浏览器”指本轮真实本地服务验收；“单测”使用 fixture，不等于真实 LLM 验收。

| 组件 / 官方 GitHub | 版本与许可证 | 实际位置 / 采用原因 | 验证与限制 |
| --- | --- | --- | --- |
| [shadcn/ui](https://github.com/shadcn-ui/ui) | 源码快照；MIT | `components/ui/upstream/` 的 Button、Card、Tabs、Dialog、Tooltip、DropdownMenu、Command、Resizable；兼容包装保留原 Button/Card 调用；文件菜单、重命名/删除/恢复确认、快照对比、命令搜索 | 浏览器及单测；保留 Radix 焦点/键盘语义。按需复制，未引入整套演示站 |
| [Radix UI](https://github.com/radix-ui/primitives) / [cmdk](https://github.com/pacocoursey/cmdk) | 1.7.0 / 1.1.1；MIT | shadcn 底层原语；真实文件搜索、保存/运行/布局命令，Ctrl/Cmd+K | 浏览器搜索并打开文件；Tabs 方向键、Dialog Escape/焦点返回、禁用命令单测 |
| [Motion](https://github.com/motiondivision/motion) | 14.1.0；MIT | `App.tsx` 路由淡入淡出；Dashboard 创建表单；概念详情展开；IDE 模式指示、画布淡入、非阻塞建议；Mentor 思考状态 | 页面/模式切换浏览器；MotionConfig reducedMotion=user；高度动画及复制组件额外 useReducedMotion |
| [Motion Primitives](https://github.com/ibelick/motion-primitives) | AnimatedGroup 源码快照；MIT | MentorPanel 的真实教学决策气泡，采用轻量 fade preset | API fixture 单测；历史空态与 disabled Provider 503 浏览器。没有为了展示动效调用真实 LLM |
| [Magic UI](https://github.com/magicuidesign/magicui) | BlurFade 源码快照；MIT | Dashboard 真实项目卡片轻微淡入/模糊；避免编码区装饰 | 创建项目与卡片浏览器；reduced motion 关闭位移、模糊和延迟，组件单测 |
| [Monaco Editor](https://github.com/microsoft/monaco-editor) / [monaco-react](https://github.com/suren-atoyan/monaco-react) | 0.57.0 / 4.7.0；MIT | 原编辑器继续负责文件编辑、语法服务、行号；统一 projectweave 主题；新增 CodeDiff 用于历史快照与 AI 真实补丁提案只读对比 | 真实编辑/保存/重读/快照 Diff 浏览器；Mentor 对比使用 API fixture 单测。提案只有说明或目标未打开时明确提示，不伪造代码；不自动应用 |
| [React Flow](https://github.com/xyflow/xyflow) | @xyflow/react 12.12.0；MIT | ConceptsPage 图视图：真实知识库先修关系、掌握证据、自定义节点、缩放/平移/拖动、Controls、MiniMap、节点详情定位 | 浏览器显示 17 节点/21 边；没有关系的缺失 ID 不造节点（单测）；保留 React Flow attribution。画布修改不写回知识库 |
| [ELK.js](https://github.com/kieler/elkjs) | 0.12.0；EPL-2.0 OR GPL-3.0-or-later，选择 EPL-2.0 | ConceptGraph 使用真实 ELK layered 自动布局、重新布局与错误重试；仅进入图视图后加载 | 真实浏览器布局成功。非 MIT，见下方发行义务；大图性能尚未验收 |
| [Dockview](https://github.com/dockview/dockview) | dockview-react / dockview / dockview-core 8.4.1；MIT | WorkspaceLayout：9 个独立面板，拖动拆分/合并、缩放、工作区内悬浮、隐藏/恢复、专注、按项目和模式保存 | 实际库组件单测与浏览器拖动/刷新/锁定验收；未引入 Enterprise；悬浮在当前工作区内，不创建浏览器弹出窗口 |
| [react-resizable-panels](https://github.com/bvaughn/react-resizable-panels) | 4.14.3；MIT | 原固定分栏实现已由 Dockview 替换；保留 upstream/resizable.tsx 作为通用原语 | 原分栏验收属于先前重建阶段；当前 IDE 布局能力由 Dockview 提供 |
| [xterm.js](https://github.com/xtermjs/xterm.js) | @xterm/xterm 6.0.0 / addon-fit 0.11.0；MIT | BottomPanel 懒加载 XtermOutput；真实 Worker 流式输出、颜色、自动 Fit、滚动、清空、错误；测试过程日志沿用真实运行管线 | 实际输出 Hello, ProjectWeave!；异常如实呈现；用户输出控制字符剥离单测。只读输出，禁止 stdin；远程 Shell 明确标注 P4 未连接 |
| [Lucide](https://github.com/lucide-icons/lucide) | 1.55.0；ISC，含 Feather 衍生图标 MIT 声明 | AppShell、项目卡片、文件树、模式锁定、菜单、shadcn 图标统一 | 浏览器；完整双来源版权声明保留 |
| [CVA](https://github.com/joe-bell/cva) / [clsx](https://github.com/lukeed/clsx) / [tailwind-merge](https://github.com/dcastil/tailwind-merge) | 0.7.1 Apache-2.0 / 2.1.1 MIT / 3.7.0 MIT | `lib/utils.ts` 与 shadcn 变体/类名合并，维持兼容 Button API | 构建、公共组件及业务页面单测 |

## 复制来源与许可证保留

- shadcn 来源：[new-york-v4/ui](https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/ui)，文件 `button/card/tabs/dialog/tooltip/dropdown-menu/command/resizable.tsx`。
- Magic UI：[blur-fade.tsx](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/blur-fade.tsx)。
- Motion Primitives：[animated-group.tsx](https://github.com/ibelick/motion-primitives/blob/main/components/core/animated-group.tsx)。其许可证源文件为 `LICENCE.md`。
- 定制：本地 cn/import 路径、项目颜色 token、中文文案、React 19 类型适配、减少动态效果处理。保留上游交互原语和版权，未重写通用弹窗/菜单/命令/分栏。
- `frontend/public/licenses/` 保留上述源码与直接 UI 依赖的完整原始许可证；`NOTICE.txt` 随 Vite public 目录一起发布，AppShell 提供访问入口。本清单不是所有已有/传递依赖的完整法律审计。
- ELK 未修改、单独懒加载，采用 EPL-2.0。依据 [上游许可证 §3](https://github.com/kieler/elkjs/blob/master/LICENSE.md)，发行时保留许可/版权，并说明 EPL 覆盖源码可获取及获取方式。NOTICE 提供精确版本 npm 源包与 gitHead `ff5771d7165445c42c408bb8a090c8035272218c` 的构建源码入口（npm 元数据核验）；之后若修改 ELK 覆盖代码，必须同步发布对应源码与声明。不可把 EPL 当作 MIT 无义务发行。
- 未引入 tldraw、GSAP、React Bits、D3、PixiJS、Excalidraw、dnd-kit、Recharts：本切片没有相应真实需求；不存在为凑库数而安装的依赖。

## 统一设计系统

样式真源为 `frontend/src/index.css`，Monaco/xterm/React Flow 主题与其对应；shadcn 语义 token 映射到同一组颜色。

| 类型 | 约定 |
| --- | --- |
| 表面 | app `#151517` → panel `#1b1b1f` → panel-2 `#242429`；编辑区 `#171719`；edge `#36363d` / soft `#2b2b31` |
| 文字 | ink `#eeeef2`；dim `#bdbdc8`；faint `#9797a6`；正文 14–15px，代码 14px / 行高 23px，IDE 正文 12–13px，元信息 11px |
| 操作/状态 | 主按钮柔紫 `#b5a5fc` 配深色字 `#211a39`；accent `#c1b5ff` / soft `#302b42`；成功 `#83d5a6`、警告 `#e8bf6a`、错误 `#f08080` |
| 字体 | 系统无衬线 + 微软雅黑中文回退；代码 Cascadia Code / Consolas；未下载或承诺用户未安装的字体 |
| 间距/圆角 | 4px 基础步进；IDE 面板内边距 12–16px，页面卡片 20–28px；半径 4/6/8/12px；仅页面卡片使用轻微阴影 |
| Hover/Active/Focus | Hover 提升灰色表面；导航/模式 Active 灰色表面配少量紫色图标或指示；2px 可见焦点环；禁用按钮阻止执行并降低强调 |
| 动画 | 普通 200ms，快速 140ms；ease `[0.16,1,0.3,1]`；模式指示使用 Motion spring；卡片轻量 250ms；不动画化拖动尺寸 |
| 减少动态效果 | MotionConfig 尊重 OS；BlurFade/AnimatedGroup 无位移模糊；折叠高度时长为 0；CSS reduced-motion 回退。已单测模拟偏好，未声称实测系统设置切换 |
| 密度/布局 | IDE 顶栏 64px、停靠标签栏 38px、编辑器工具栏 48px、状态栏 28px；桌面最低 960px；编辑器最小 260×150px、其他面板 170×100px；1440/1920 桌面验收；首页 390px 窄屏验收，手机 IDE 未验收 |

业务错误继续通过 ApiError 与可见错误提示处理；Dialog 提供标题/描述，Tabs 正确关联面板，命令继承 cmdk 键盘搜索；Dockview 提供停靠拖动和约束，面板菜单使用 Radix 键盘操作。

### 复用方式

业务页面从兼容包装导入 Button/Card，通用弹窗和菜单从 upstream 导入，避免再造一套原语。
按钮 `primary/outline/ghost/danger`、`sm/md` 保持旧调用；导航通过 asChild 保留链接语义。

```tsx
<Button asChild variant="outline"><Link to="/concepts">知识图谱</Link></Button>
<PanelTabs value={tab} onChange={setTab}
  items={[{ id: 'files', label: '文件' }, { id: 'history', label: '历史' }]}
  label="项目资源">{content}</PanelTabs>
<Dialog>
  <DialogTrigger asChild><Button>查看差异</Button></DialogTrigger>
  <DialogContent>
    <DialogTitle>代码差异</DialogTitle>
    <DialogDescription>只读比较，不应用修改。</DialogDescription>
    {diffContent}
  </DialogContent>
</Dialog>
```

新图只有真实节点与边数据可接入时才使用 React Flow；新动画优先复用全局 Motion 配置，并为高度/模糊等属性处理减少动态效果。

## 性能与真实运行验收

`npm run verify`（自由布局完成后）：typecheck 零错误、33 个测试文件 / 201 个用例通过、Vite 生产构建通过。
开源组件重建阶段后端 `.venv/Scripts/python.exe -m pytest`：123 passed / 4 skipped（可选 PostgreSQL 套件未执行）；随后的纯视觉调整未改后端、未重复后端验证。

构建输出（视觉调整前首次重建，minified / gzip，十进制 kB）：入口 JS 467.98 / 151.42；React Flow 图模块 182.09 / 59.21；xterm 334.05 / 84.48；ELK 1430.71 / 441.94；Monaco editor.api 2735.70 / 705.08；TS 转译器 3451.81 / 970.18。
Monaco language workers 包括 TS worker 6928.03 kB。构建仍报告大于 500kB 的警告，未关闭警告或增大阈值掩盖。
路由 lazy/Suspense，图视图与 ELK、终端、Diff、TS 编译器均按使用场景延迟加载；入口体积不是全部按需 chunk 的总下载量。ELK 当前17节点验收不代表超大图性能保证。
自由布局完成后的入口 JS 469.03 / 151.74 kB，IDE 路由 JS 655.22 / 166.03 kB，IDE CSS 127.03 / 10.36 kB。Dockview 增加 IDE 路由下载体积，仍随 IDE 路由延迟加载；大体积警告保留。

真实服务在独立 SQLite 验收数据库启动，`PW_AI_PROVIDER=disabled`，未调用真实 LLM。
验收创建的项目名称为“组件重建验收”，文件、保存、快照均由 API 持久化，不是业务 mock。

| 检查 | 结果 |
| --- | --- |
| 1440×900 / 1920×1080 | 页面真实渲染；IDE 无横向溢出；分栏、编辑器、Mentor、底部输出可见 |
| 布局 | 鼠标拖动到中央合并、到边缘拆分、分隔线缩放；按项目/模式保存，刷新恢复拆分与比例；锁定拒绝拖动与菜单调整；移动/隐藏保留 Monaco 撤销记录与导师输入 |
| 文件与快照 | Monaco 编辑→保存→重新打开读回；新快照可立即出现；Diff 双编辑器只读；重命名 Dialog 的取消和菜单可用；新页面连续3次打开/关闭 Diff，无控制台异常 |
| 命令/运行/测试 | 搜索 main.test.ts 并打开；实际 Worker 输出 Hello, ProjectWeave!；真实种子测试 2 通过；错误信息与状态如实显示 |
| 教学数据 | 调试画布时间线与 observe("answer",42) 的变量状态来源于本次真实 trace；保留指纹与过期判断 |
| Mentor | disabled Provider 返回 503，显示未配置；未发送伪造 AI 回复。真实提案 Diff 数据连接通过 fixture 单测；真实 LLM 流程本轮未验收 |
| 知识图 | 真实17节点/21边 ELK 布局；缩放按钮、节点拖动/详情定位、重新布局；缺失关系单测；无浏览器控制台错误 |
| 动画/可访问性 | 页面/模式/展开过渡、公共组件键盘测试、减少动态效果分支；不以 jsdom 断言代替真实分栏和 Monaco 验收 |

验收截图保存在本次 Codex 可视化附件目录，未混入项目业务数据或生产种子。
Diff 生命周期由 `lib/diffLifecycle.ts` 在 layout cleanup 中先解除模型绑定再释放，包装库随后释放 widget；避免 [上游已报告的模型释放顺序问题](https://github.com/suren-atoyan/monaco-react/issues/647)，同时不遗留持久模型。相关顺序约束有单测。

### 视觉细化（2026-10-10）

用户确认采用“石墨灰＋柔紫，精致开发工具风”。此轮统一页面、Monaco、xterm、知识图的灰色表面；主操作使用柔紫，导航与模式选中使用灰色表面，减少整块彩色高亮与重复描边。

- 首页采用项目主列表与学习入口侧栏；所有项目、日期和跳转均来自真实数据；新增工作区和诊断入口有路由断言。
- 首页与知识页统一大标题、正文行高和内容宽度；侧栏采用交织线条标识与清晰选中状态。
- 工作区扩大工具栏留白、文件行与代码字号，关闭 Monaco 缩略图；Mentor 统一空态与输入框，发送按钮保留可访问名称与原发送逻辑。
- 标准场景显示“运行时间线 / 变量状态 / 运行与状态”；模板 ID 保留在 title 与支持键盘焦点的 Radix Tooltip 中，交互提示移入同一 Tooltip；来源、运行时间、指纹与过期提示继续显示。
- 再次执行 `npm run verify`：32 文件 / 191 用例、typecheck 与 build 通过。浏览器检查 1440×900、1920×1080 工作区与 390px 首页，无横向溢出；真实 Worker 输出与 observe 数据正常，验收标签页无 warn/error。大体积构建警告仍保留。

### 自由视图模式（2026-10-10）

文件、任务、历史、编辑器、教学画布、AI 导师、终端、测试、学习事件为 9 个独立面板。四种工作模式只提供初始布局，每种模式都允许自由调整。

- 拖动标题到目标中央合并为标签页，到目标边缘拆分；拖动分隔线调整大小。
- 标签上的关闭按钮仅隐藏面板；顶栏「视图」可显示/隐藏任意面板，包括全部隐藏后的恢复。Ctrl/Cmd+K 也提供显示面板和恢复布局命令。
- 面板右上菜单支持移动到工作区四边、与指定面板合并、在工作区内悬浮。悬浮面板可以拖动、调整大小和重新停靠。
- 停靠组支持专注/退出专注；悬浮组不提供无效的专注按钮。恢复默认布局只重置当前模式。
- `pw-dock-layout-v1:${projectId}:${mode}` 保存几何、分组、标签和可见状态；刷新恢复。只接受注册面板与有限结构，剥离业务参数；损坏/不可用存储通过 ErrorBanner 明示并回退。
- 布局锁定同时禁用模式切换、拖动/缩放、隐藏/显示、移动/合并、悬浮和重置；已有标签页仍可切换，真实编辑/运行不受影响。
- 稳定 React portal 宿主让移动、隐藏、重置和切换模式不会卸载 Monaco/导师。当前页面中的撤销记录、草稿、未发送输入保持；不承诺完整刷新后的撤销记录或导师输入持久化。
- v8 的 `keyboardNavigation` 属于 Enterprise，本项目未启用；可通过 Radix 菜单键盘执行移动、合并、悬浮和显隐，不宣称提供 Enterprise 快捷键。

6 个新增测试使用实际 DockviewReact，覆盖状态保持、存储隔离/白名单、全隐藏恢复、锁定拒绝、悬浮、损坏回退。浏览器验证中央合并、边缘拆分、缩放、锁定拒绝拖动、模式独立恢复、刷新恢复、悬浮、专注与导师输入保持；真实 Monaco 添加注释→隐藏/恢复→撤销成功，真实 Worker 运行及 2 个种子测试成功。1440×900 / 1920×1080 实际布局截图已保存；最终新标签页无 warn/error。验收发现隐藏渲染器的屏幕外内容可能触发焦点滚动，已在布局边界用 overflow-clip 隔离并复测。

### 界面设置与外观自定义（2026-10-10）

全站和 IDE 顶栏「设置」以及 IDE 命令搜索打开同一设置入口。沿用 Radix Dialog/Tabs/RadioGroup/Switch 与现有 shadcn Button，不新增依赖。对话框固定标题/分类/页脚，内容单独滚动；390px 下设置行上下排列，放大到 120% 仍无横向溢出；边界 overflow-clip 防止键盘焦点滚动隐藏固定标题。

| 分类 | 实际设置 |
| --- | --- |
| 外观与动效 | 石墨灰/午夜蓝/浅色纸张；5 色板和自定义 #RRGGBB；相对字号 90–120%；紧凑/适中/宽松；圆角 0–16px；纯色/点阵/网格；卡片阴影与动效 |
| 编辑器与终端 | Cascadia Code/JetBrains Mono/系统等宽（本机字体回退）；代码 11–22px、行高 1.3–2；换行/行号/缩略图/连字；终端 11–20px |
| 工作区布局 | 实时锁定、9 面板显隐、恢复当前模式默认布局；进入 IDE 才展示真实面板开关 |

外观即时应用并保存在当前浏览器 `pw-appearance-v1`（version 1）；不跨设备同步，也不主动同步已打开的其他标签页。新页面/刷新读取保存值。schema 限制范围、颜色格式与字段，损坏回退和不可写错误在设置内明确显示；「恢复默认外观」只重置外观，不改变布局、锁定、AI 介入偏好。界面字号改变 rem 相对尺寸，固定像素元素与代码字号独立。

所有主题映射页面、编辑器、终端与知识图；强调色文字按表面调整对比度，按钮填色保留输入色。动态关闭同步禁用 CSS/Motion；系统减少动态效果始终生效。主题切换保留 Monaco 实例/模型/撤销和终端缓冲；关闭模糊动画时显式清除旧 filter/transform；浅色终端日志不再使用白色文本。设置打开时 Ctrl/Cmd+S、Ctrl/Cmd+Enter 和 Ctrl/Cmd+K 不触发背后动作。

定向测试：appearance 10、实际 Dockview 7、公共 UI 8，共 25 个通过，覆盖写后可读、异常存储、颜色/范围校验、对比、键盘/焦点、非法十六进制回退、实时编辑选项、动效关闭、布局锁定和外观恢复的独立性。浏览器检查实际主题/代码/终端、刷新恢复、Monaco 主题切换后撤销、真实 Worker 输出、导师输入和布局显隐保持；1440px IDE 与390px 首页设置验收。此切片不改后端。

全量 `npm run verify`：typecheck 零错误、34 文件 / 212 用例全过、生产构建成功。入口 JS 544.43 / gzip 176.48 kB，IDE 路由 JS 619.11 / gzip 154.94 kB；设置使用全站入口，增加共享 Radix 设置控件体积。大于500kB构建警告保留。验收期间同一工作区任务验收/Tutor 契约变动造成的失败已随该切片测试更新消除，没有删除或弱化断言。

### 首页滚动边界修复（2026-10-10）

复现时 1920×1080 视口的 document 高度为1144px：首页 min-height:100% 占了1080px，另有64px顶栏，短内容也能整页滚动，顶部设置入口随之消失。AppShell 改为固定 100dvh + flex 列，顶栏不压缩，正文 min-height:0 占剩余空间独立滚动；侧栏留在窗口内。正文区域带可访问名称和键盘焦点。

实际浏览器修复后 document=1080px、正文 clientHeight=scrollHeight=1016px，滚轮不再移动短页面。展开表单时正文溢出仍可滚动；390×844 正文以 Ctrl+End 滚至466px（scrollHeight1246/clientHeight780），页尾可见，window.scrollY=0、顶栏 top=0。`npm run verify` 34文件/212测试、typecheck/build 通过，大体积构建警告保留。本次为页面壳修复，无后端变更。

## 明确留到后续的功能

- 静态分析架构图、任务依赖图、状态机/调用图、源码双向定位：尚无相应数据接入，本轮 React Flow 使用知识图；架构画布继续明确“未实现 / P3”。
- AI 代码区域高亮、行内教学提示：未实现。WorkspaceAction 宿主应用/确认已在独立 P3.4 切片接入，详见 PROGRESS.md；真实 LLM 补丁未在本轮浏览器验收。
- 课程任务状态变化/完成反馈动画、学习档案统计/开发历程：本轮未添加；仍保留真实任务验收逻辑。
- 远程交互 Shell/stdin、多文件 import、远程隔离沙箱：P4/按原计划；xterm 显示实际 Worker 输出，未伪装 shell。
- 边缘自动收起面板、大图 Web Worker 布局：未实现；自由面板隐藏/恢复与跨模式 Monaco 保持已实现。
