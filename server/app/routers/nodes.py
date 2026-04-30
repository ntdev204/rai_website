from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth import get_current_user
from app.models.node_state import NodeState
from app.services.zmq_bridge import send_scada_command

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("/", dependencies=[Depends(get_current_user)])
async def list_nodes(db: AsyncSession = Depends(get_db)):
    reply = await send_scada_command("list_nodes", timeout_ms=3000)
    if reply.get("status") in {"ok", "success"} and isinstance(reply.get("nodes"), list):
        return [
            {
                "id": index + 1,
                "node_name": str(node.get("node_name") or node.get("name") or ""),
                "package_name": node.get("package_name"),
                "status": node.get("status") or "active",
                "source": node.get("source") or reply.get("source") or "raspi_ros2",
                "last_changed_at": node.get("last_changed_at") or reply.get("timestamp"),
                "changed_by_user_id": None,
                "metadata": node.get("metadata") or {},
            }
            for index, node in enumerate(reply["nodes"])
            if isinstance(node, dict)
        ]

    rows = (await db.execute(select(NodeState).order_by(NodeState.node_name))).scalars().all()
    return [
        {
            "id": row.id,
            "node_name": row.node_name,
            "package_name": row.package_name,
            "status": row.status,
            "source": "database_fallback",
            "last_changed_at": row.last_changed_at,
            "changed_by_user_id": row.changed_by_user_id,
        }
        for row in rows
    ]
