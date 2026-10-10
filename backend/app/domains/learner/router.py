"""学习者模型路由（只读；证据由诊断等来源经 service 写入）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.learner import service
from app.domains.learner.schemas import MasteryList, MasteryRead

router = APIRouter(prefix="/mastery", tags=["learner"])


@router.get("", response_model=MasteryList, summary="当前用户的概念掌握估计")
def list_mastery(db: Session = Depends(get_db)) -> MasteryList:
    # owner_id 来自身份体系（P1.7 未接入），当前为开发模式占位。
    records = service.list_mastery(db, "dev-user")
    return MasteryList(
        items=[MasteryRead.model_validate(r) for r in records], total=len(records)
    )
