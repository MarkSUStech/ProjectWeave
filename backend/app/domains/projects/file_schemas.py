"""项目文件（工作区）的 API 契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domains.projects.schemas import APIModel


class FileMeta(APIModel):
    path: str
    size: int
    updatedAt: datetime


class FileList(APIModel):
    items: list[FileMeta]
    total: int


class FileRead(APIModel):
    path: str
    content: str
    updatedAt: datetime


class FileWrite(APIModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=1_000_000)


class FileRename(APIModel):
    path: str = Field(min_length=1, max_length=500)
    new_path: str = Field(min_length=1, max_length=500)


class SnapshotMeta(APIModel):
    id: UUID
    path: str
    size: int
    sha256: str
    createdAt: datetime


class SnapshotList(APIModel):
    items: list[SnapshotMeta]
    total: int


class SnapshotRead(APIModel):
    id: UUID
    path: str
    content: str
    sha256: str
    createdAt: datetime


class CodeVersionInfo(APIModel):
    codeVersion: str
    fileCount: int
