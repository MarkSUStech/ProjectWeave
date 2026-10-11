"""GitHub 仓库适配器（P7.1）：公开仓库只读导入，限额与不可信内容处理。

- 仅支持公开仓库（第一版）；可选 PW_GITHUB_TOKEN 提升限额；
- 可配置 API/Raw 基址（PW_GITHUB_API_BASE / PW_GITHUB_RAW_BASE）——
  网络受限环境可指向镜像（E2E 用）；
- 限额：文件数 ≤800、单文件 ≤512KB、快照总量 ≤3MB、树深度 ≤12；
- 二进制/锁文件/超大文件过滤；只读取文本内容进快照；
- 403/429 明确报"速率限制"，404 报"仓库不存在/不可访问"；
- LICENSE 缺失或不明确 → needs_review（绝不自动认定可再发布）；
- 全部内容视为不可信数据（防提示注入由上层 context 包裹处理）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from app.core.config import settings


class GitHubAdapterError(Exception):
    """仓库导入失败（含明确原因）。"""


class GitHubRateLimitedError(GitHubAdapterError):
    pass


class GitHubNotFoundError(GitHubAdapterError):
    pass


_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

MAX_FILES = 800
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_TREE_DEPTH = 12

# 二进制与无教学价值文件的扩展名/目录过滤
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svgz", ".webp",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov", ".pyc", ".class", ".jar", ".wasm",
    ".o", ".a", ".lib", ".obj", ".pdb", ".ipynb", ".db", ".sqlite",
}
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".idea", ".vscode", "target", ".pytest_cache", ".mypy_cache",
}
# 有教学价值的文本扩展白名单（不在名单内的文本文件保留树条目但不读内容）
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".cpp", ".cc", ".cxx", ".c", ".h",
    ".hpp", ".java", ".go", ".rs", ".rb", ".md", ".txt", ".rst", ".toml",
    ".yaml", ".yml", ".json", ".cfg", ".ini", ".sh", ".bash", ".html", ".css",
    ".scss", ".cmake", ".mk", "makefile", "dockerfile", "requirements",
    "license", "manifest",
}

LICENSE_PATTERNS = [
    ("MIT", r"MIT License"),
    ("Apache-2.0", r"Apache License"),
    ("BSD-2-Clause", r"Redistribution and use in source and binary forms"),
    ("BSD-3-Clause", r"Redistribution and use in source and binary forms,? with(?:out)? modification"),
    ("GPL-3.0", r"GNU GENERAL PUBLIC LICENSE"),
    ("GPL-2.0", r"GNU General Public License"),
    ("LGPL", r"GNU LESSER GENERAL PUBLIC LICENSE"),
    ("MPL-2.0", r"Mozilla Public License"),
    ("Unlicense", r"This is free and unencumbered software released into the public domain"),
]


def parse_github_url(url: str) -> tuple[str, str]:
    """解析标准 GitHub 仓库 URL → (owner, repo)；非法即抛错。"""
    match = _URL_RE.match(url.strip())
    if not match:
        raise GitHubAdapterError(
            "非法 GitHub 仓库 URL（期望 https://github.com/<owner>/<repo>）"
        )
    owner, repo = match.group(1), match.group(2)
    if owner.lower() in ("orgs", "topics", "settings") :
        raise GitHubAdapterError("非法仓库路径")
    return owner, repo


@dataclass
class RepoSnapshot:
    """仓库快照：元数据 + 目录树 + 限额内文本文件内容。"""

    owner: str
    repo: str
    default_branch: str
    commit_sha: str
    meta: dict
    tree: list[dict] = field(default_factory=list)  # [{path, type, size}]
    files: dict[str, str] = field(default_factory=dict)  # path → content
    license: dict = field(default_factory=dict)  # {spdx|None, source, needs_review}
    stats: dict = field(default_factory=dict)  # 限额与过滤统计


class GitHubAdapter:
    def __init__(self, api_base: str | None = None, raw_base: str | None = None,
                 token: str | None = None, transport=None, timeout: float = 30.0):
        self.api_base = (api_base or getattr(settings, "github_api_base", "") or
                         "https://api.github.com").rstrip("/")
        self.raw_base = (raw_base or getattr(settings, "github_raw_base", "") or
                         "https://raw.githubusercontent.com").rstrip("/")
        self.token = token or getattr(settings, "github_token", "") or ""
        self.timeout = timeout
        self._client = httpx.Client(transport=transport) if transport is not None else httpx

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, url: str, *, raw: bool = False) -> httpx.Response:
        try:
            resp = self._client.get(
                url,
                headers={} if raw else self._headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise GitHubAdapterError(f"GitHub 网络错误：{exc}") from exc
        if resp.status_code in (403, 429):
            raise GitHubRateLimitedError(
                "GitHub API 速率限制（可配置 PW_GITHUB_TOKEN 提升限额，稍后重试）"
            )
        if resp.status_code == 404:
            raise GitHubNotFoundError("仓库不存在或不可访问（仅支持公开仓库）")
        if resp.status_code != 200:
            raise GitHubAdapterError(f"GitHub API 返回 {resp.status_code}：{resp.text[:200]}")
        return resp

    # ---------------------------------------------------------------- 步骤

    def fetch_snapshot(self, url: str) -> RepoSnapshot:
        """导入仓库快照：元数据 → 默认分支 commit → 树 → 限额内文本文件。"""
        owner, repo = parse_github_url(url)

        # 1. 元数据（默认分支/描述/语言/许可证线索）
        meta_resp = self._get(f"{self.api_base}/repos/{owner}/{repo}")
        meta = meta_resp.json()
        default_branch = meta.get("default_branch") or "main"
        license_hint = (meta.get("license") or {}).get("spdx_id")

        # 2. 固定 commit SHA（结果可复现）
        commit = self._get(
            f"{self.api_base}/repos/{owner}/{repo}/commits/{default_branch}"
        ).json()
        commit_sha = commit.get("sha") or ""
        if not commit_sha:
            raise GitHubAdapterError("无法获取默认分支 commit SHA")

        # 3. 目录树（递归）
        tree_resp = self._get(
            f"{self.api_base}/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
        ).json()
        raw_entries = tree_resp.get("tree", [])
        if tree_resp.get("truncated"):
            raise GitHubAdapterError("仓库目录树过大（truncated），暂不支持")

        snapshot = RepoSnapshot(owner=owner, repo=repo, default_branch=default_branch,
                                commit_sha=commit_sha, meta={
            "description": meta.get("description"),
            "language": meta.get("language"),
            "topics": meta.get("topics") or [],
            "stars": meta.get("stargazers_count"),
        })

        # 4. 过滤与限额
        total = 0
        for entry in raw_entries:
            path = entry.get("path", "")
            if not path or path.count("/") >= MAX_TREE_DEPTH:
                continue
            top = path.split("/")[0].lower()
            if top in IGNORED_DIRS:
                continue
            etype = entry.get("type")
            size = entry.get("size") or 0
            snapshot.tree.append({"path": path, "type": etype, "size": size})
            if etype == "blob" and size <= MAX_FILE_BYTES:
                snapshot.stats.setdefault("candidates", []).append(path)

        if len(snapshot.tree) > MAX_FILES * 3:
            raise GitHubAdapterError(f"仓库文件数超上限（树条目 {len(snapshot.tree)}）")

        # 5. 拉取文本内容（白名单扩展 + 限额）
        candidates = snapshot.stats.pop("candidates")
        skipped_binary = 0
        for path in sorted(candidates)[:MAX_FILES]:
            lower = path.lower()
            name = lower.rsplit("/", 1)[-1]
            stem_ext = name.rsplit(".", 1)
            ext = "." + stem_ext[-1] if len(stem_ext) > 1 else ""
            is_text = ext in TEXT_EXTENSIONS or name in {
                "makefile", "dockerfile", "license", "notice", "requirements",
            } or "license" in name or "manifest" in name
            if not is_text or any(lower.endswith(b) for b in BINARY_EXTENSIONS):
                skipped_binary += 1
                continue
            if total > MAX_TOTAL_BYTES:
                snapshot.stats["content_truncated"] = True
                break
            content = self._fetch_file_content(owner, repo, commit_sha, path)
            if content is None:
                continue  # 单文件失败不阻塞快照
            if len(content.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
                skipped_binary += 1
                continue
            snapshot.files[path] = content
            total += len(content.encode("utf-8", errors="ignore"))

        snapshot.stats.update({
            "treeEntries": len(snapshot.tree),
            "textFiles": len(snapshot.files),
            "totalBytes": total,
            "skippedBinary": skipped_binary,
        })

        # 6. LICENSE 识别（不明确 → needs_review）
        snapshot.license = self._detect_license(snapshot.files, license_hint)
        return snapshot

    def _fetch_file_content(self, owner: str, repo: str, sha: str, path: str) -> str | None:
        """文件内容：raw 直连优先，失败回退 GitHub API contents（base64）。

        raw.githubusercontent 在部分网络不可达——API 端点兜底保证可复现导入。
        """
        try:
            return self._get(f"{self.raw_base}/{owner}/{repo}/{sha}/{path}", raw=True).text
        except GitHubAdapterError:
            pass
        try:
            import base64

            data = self._get(
                f"{self.api_base}/repos/{owner}/{repo}/contents/{path}?ref={sha}"
            ).json()
            encoded = data.get("content")
            if data.get("encoding") == "base64" and encoded:
                return base64.b64decode(encoded).decode("utf-8", errors="replace")
        except (GitHubAdapterError, Exception):
            return None
        return None

    def _detect_license(self, files: dict[str, str], hint: str | None) -> dict:
        license_path = next(
            (p for p in files if p.upper().rsplit("/", 1)[-1].startswith("LICENSE")),
            None,
        )
        if license_path:
            text = files[license_path][:4000]
            for spdx, pattern in LICENSE_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    return {"spdx": spdx, "source": license_path, "needs_review": False}
            # 有 LICENSE 文件但匹配失败 → 需人工审查
            return {"spdx": None, "source": license_path, "needs_review": True,
                    "note": "LICENSE 内容未能确定性识别，需人工审查"}
        if hint and hint not in ("NOASSERTION", "NONE", None):
            return {"spdx": hint, "source": "github-api", "needs_review": False}
        return {"spdx": None, "source": None, "needs_review": True,
                "note": "仓库未包含可识别的 LICENSE 文件——再发布/复制源码前需人工审查"}

    def to_dict(self, snap: RepoSnapshot) -> dict:
        return {
            "owner": snap.owner, "repo": snap.repo,
            "defaultBranch": snap.default_branch, "commitSha": snap.commit_sha,
            "meta": snap.meta, "tree": snap.tree, "files": snap.files,
            "license": snap.license, "stats": snap.stats,
        }

    @staticmethod
    def from_dict(data: dict) -> RepoSnapshot:
        return RepoSnapshot(
            owner=data["owner"], repo=data["repo"],
            default_branch=data["defaultBranch"], commit_sha=data["commitSha"],
            meta=data.get("meta") or {}, tree=data.get("tree") or [],
            files=data.get("files") or {}, license=data.get("license") or {},
            stats=data.get("stats") or {},
        )
