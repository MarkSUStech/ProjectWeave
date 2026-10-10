# 空的根 conftest：让 pytest 将 backend/ 加入 sys.path，
# 并在任何 app 导入之前关闭启动迁移与真实 AI（测试使用 Mock Provider 注入）。
import os

os.environ.setdefault("PW_AUTO_MIGRATE", "false")
os.environ.setdefault("PW_AI_PROVIDER", "disabled")
os.environ.setdefault("PW_DEEPSEEK_API_KEY", "")
