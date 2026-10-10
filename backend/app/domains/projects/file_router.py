"""项目文件的路由（挂载于 /projects/{project_id}/files）与快照/版本端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.projects import file_service, service
from app.domains.projects.file_schemas import (
    CodeVersionInfo,
    FileList,
    FileMeta,
    FileRead,
    FileRename,
    FileWrite,
    SnapshotList,
    SnapshotMeta,
    SnapshotRead,
)
from app.domains.projects.file_service import FileError
from app.domains.projects.service import ProjectNotFoundError

router = APIRouter(prefix="/projects/{project_id}/files", tags=["project-files"])
project_router = APIRouter(prefix="/projects/{project_id}", tags=["project-files"])


def _ensure_project(db: Session, project_id: str) -> None:
    try:
        service.get_project(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


def _file_meta(file) -> FileMeta:
    return FileMeta(path=file.path, size=len(file.content), updatedAt=file.updated_at)


@router.get("", response_model=FileList, summary="文件列表（扁平路径，按路径排序）")
def list_files(project_id: str, db: Session = Depends(get_db)) -> FileList:
    _ensure_project(db, project_id)
    files = file_service.list_files(db, service.parse_project_id(project_id))
    return FileList(items=[_file_meta(f) for f in files], total=len(files))


@router.get("/content", response_model=FileRead, summary="读取文件内容")
def read_file(
    project_id: str,
    path: str = Query(min_length=1, max_length=500),
    db: Session = Depends(get_db),
) -> FileRead:
    _ensure_project(db, project_id)
    try:
        file = file_service.read_file(db, service.parse_project_id(project_id), path)
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return FileRead(path=file.path, content=file.content, updatedAt=file.updated_at)


@router.put(
    "",
    response_model=FileMeta,
    status_code=status.HTTP_201_CREATED,
    summary="创建/整体替换文件",
)
def write_file(project_id: str, payload: FileWrite, db: Session = Depends(get_db)) -> FileMeta:
    _ensure_project(db, project_id)
    try:
        file, _created = file_service.write_file(
            db, service.parse_project_id(project_id), payload.path, payload.content
        )
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    # 学习事件：保存行为（确定性 eventId，同次保存重复投递会被幂等跳过）
    from datetime import datetime, timezone

    from app.domains.events.service import append_event, server_event_id

    append_event(
        db,
        event_id=server_event_id("file-saved", str(file.project_id), file.path, file.updated_at.isoformat()),
        type="file-saved",
        occurred_at=datetime.now(timezone.utc),
        aggregate_id=f"project:{file.project_id}",
        project_id=file.project_id,
        payload={"path": file.path, "size": len(file.content)},
    )
    return _file_meta(file)


@router.patch("", response_model=FileMeta, summary="重命名/移动文件")
def rename_file(project_id: str, payload: FileRename, db: Session = Depends(get_db)) -> FileMeta:
    _ensure_project(db, project_id)
    try:
        file = file_service.rename_file(
            db,
            service.parse_project_id(project_id),
            payload.path,
            payload.new_path,
        )
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _file_meta(file)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="删除文件")
def delete_file(
    project_id: str,
    path: str = Query(min_length=1, max_length=500),
    db: Session = Depends(get_db),
) -> Response:
    _ensure_project(db, project_id)
    try:
        file_service.delete_file(db, service.parse_project_id(project_id), path)
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# 快照历史与 codeVersion
# ---------------------------------------------------------------------------


@project_router.get("/code-version", response_model=CodeVersionInfo, summary="项目当前代码指纹")
def get_code_version(project_id: str, db: Session = Depends(get_db)) -> CodeVersionInfo:
    _ensure_project(db, project_id)
    info = file_service.compute_code_version(db, service.parse_project_id(project_id))
    return CodeVersionInfo(**info)


@router.get("/history", response_model=SnapshotList, summary="文件快照历史（倒序）")
def list_file_history(
    project_id: str,
    path: str = Query(min_length=1, max_length=500),
    db: Session = Depends(get_db),
) -> SnapshotList:
    _ensure_project(db, project_id)
    try:
        snapshots = file_service.list_snapshots(db, service.parse_project_id(project_id), path)
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return SnapshotList(
        items=[
            SnapshotMeta(
                id=s.id,
                path=s.path,
                size=len(s.content),
                sha256=s.content_sha256[:12],
                createdAt=s.created_at,
            )
            for s in snapshots
        ],
        total=len(snapshots),
    )


@router.get("/history/{snapshot_id}", response_model=SnapshotRead, summary="读取快照内容")
def read_snapshot(project_id: str, snapshot_id: str, db: Session = Depends(get_db)) -> SnapshotRead:
    _ensure_project(db, project_id)
    try:
        pid = service.parse_project_id(project_id)
        sid = service.parse_project_id(snapshot_id)
        snapshot = file_service.get_snapshot(db, pid, sid)
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return SnapshotRead(
        id=snapshot.id,
        path=snapshot.path,
        content=snapshot.content,
        sha256=snapshot.content_sha256,
        createdAt=snapshot.created_at,
    )


@router.post(
    "/history/{snapshot_id}/restore",
    response_model=FileMeta,
    summary="恢复快照（当前内容先入历史）",
)
def restore_snapshot(project_id: str, snapshot_id: str, db: Session = Depends(get_db)) -> FileMeta:
    _ensure_project(db, project_id)
    try:
        pid = service.parse_project_id(project_id)
        sid = service.parse_project_id(snapshot_id)
        file = file_service.restore_snapshot(db, pid, sid)
    except FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _file_meta(file)
