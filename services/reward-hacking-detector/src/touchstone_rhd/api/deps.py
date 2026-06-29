"""FastAPI dependency wiring for the RHD API.

The DB engine, knowledge base, and job runner are constructed once at app
startup and stored on ``app.state``; these dependencies expose them to handlers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..knowledge.repository import KnowledgeBase
from ..worker import EvaluationJobRunner


def get_kb(request: Request) -> KnowledgeBase:
    return request.app.state.kb


def get_runner(request: Request) -> EvaluationJobRunner:
    return request.app.state.runner


KBDep = Annotated[KnowledgeBase, Depends(get_kb)]
RunnerDep = Annotated[EvaluationJobRunner, Depends(get_runner)]
