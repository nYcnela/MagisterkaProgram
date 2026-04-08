from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProcessStatus(BaseModel):
    state: str = "STOPPED"
    details: str = ""
    pid: Optional[int] = None


class NodeSnapshot(BaseModel):
    backend: ProcessStatus = Field(default_factory=ProcessStatus)
    llm: ProcessStatus = Field(default_factory=ProcessStatus)
    run_id: str = ""
    last_feedback: str = ""
    recent_logs: List[str] = Field(default_factory=list)
    session_active: bool = False
    session_id: str = ""
    dance_id: str = ""


class WsEvent(BaseModel):
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class SessionStartRequest(BaseModel):
    session_id: str = ""
    dance_id: str
    sequence_name: str = "udp_sequence"
    step_type: str = "step"
    run_id: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class SessionStopRequest(BaseModel):
    reason: str = "remote_gui"

