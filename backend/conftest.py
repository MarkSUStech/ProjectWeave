# 空的根 conftest：让 pytest 将 backend/ 加入 sys.path，
# 并在任何 app 导入之前关闭启动迁移与真实 AI（测试使用 Mock Provider 注入）。
import os

os.environ.setdefault("PW_AUTO_MIGRATE", "false")
# PW_COURSE_E2E=1 是唯一的显式真实 LLM 豁免闸门（真实课程生成 E2E）；
# 其余所有测试保持 AI disabled + Key 清空（AGENTS 规则：Mock 注入，不调真实 LLM）。
if os.environ.get("PW_COURSE_E2E") != "1":
    os.environ.setdefault("PW_AI_PROVIDER", "disabled")
    os.environ.setdefault("PW_DEEPSEEK_API_KEY", "")
