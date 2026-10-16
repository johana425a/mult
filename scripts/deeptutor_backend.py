"""Original bridge endpoints around an unchanged DeepTutor API application."""
from __future__ import annotations
from deeptutor_runtime import configure_environment, initialize
configure_environment()
initialize()
from integration.embedding_route_guard import install_embedding_guard
install_embedding_guard()
from initialize_deepsteam import initialize as initialize_deepsteam
initialize_deepsteam()

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from deeptutor.api.main import app
from deeptutor.api.routers.auth import require_auth
from integration.deeptutor_shared_provider import install_routes
install_routes(app)


def _prewarm_first_chat():
    """DeepSteam 2026-10-16: load what the first chat turn needs in the background.

    The first message used to wait several seconds while the chat engine,
    the model client and the tokenizer were imported on demand.
    """
    import importlib
    import threading
    import time

    def run():
        import socket

        # Start only after the server is up, so nothing races its own startup.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", 8011), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        time.sleep(2)
        for name in ("deeptutor.agents.chat.capability", "deeptutor.agents.loop.pipeline",
                     "deeptutor.agents.loop.agent_loop", "deeptutor.runtime.agentic.client",
                     "openai.resources.chat", "deeptutor.services.session.context_builder"):
            try:
                importlib.import_module(name)
            except Exception:
                pass
        try:
            import tiktoken
            tiktoken.get_encoding("cl100k_base")
        except Exception:
            pass

    threading.Thread(target=run, name="deepsteam-prewarm", daemon=True).start()


_prewarm_first_chat()


class AnswerRecord(BaseModel):
    question: str = Field(min_length=1, max_length=20000)
    answer: str = Field(min_length=1, max_length=30000)
    material_id: str
    course_id: str | None = None
    session_id: str | None = None
    submission_id: str = Field(min_length=1, max_length=100)


@app.post("/api/contest/answers", dependencies=[Depends(require_auth)])
async def record_student_answer(payload: AnswerRecord, request: Request):
    """Persist the ungraded first answer in native session storage, no model."""
    # Respect auth if the user later enables native authentication.
    from deeptutor.services.session import get_session_store
    from deeptutor.services.courses import get_course_service
    store = get_session_store()
    if payload.course_id:
        try:
            get_course_service().get(payload.course_id)
        except Exception:
            raise HTTPException(404, "Course not found")
    # Use the native reading service HTTP endpoint for material validation in
    # the client; here reject an empty id without reading arbitrary paths.
    if not payload.material_id:
        raise HTTPException(422, "material_id required")
    session = await store.get_session(payload.session_id) if payload.session_id else None
    if payload.session_id and not session:
        raise HTTPException(404, "Session not found")
    if not session:
        session = await store.create_session(title="Learning answer: " + payload.question[:65])
    session_id = session.get("session_id") or session.get("id")
    # A retried submission preserves the exact first-answer row.
    for message in await store.get_messages(session_id):
        if (message.get("metadata") or {}).get("contest_submission_id") == payload.submission_id:
            return {"session_id": session_id, "record_id": message["id"], "status": "recorded", "model_called": False}
    record_id = await store.add_message(session_id, "user", "Question: " + payload.question + "\n\nStudent first answer: " + payload.answer,
        capability="chat", metadata={"contest_submission_id": payload.submission_id,
        "contest_answer": {"question": payload.question, "answer": payload.answer, "material_id": payload.material_id, "status": "ungraded"}})
    if payload.course_id:
        await store.update_session_preferences(session_id, {"course_id": payload.course_id})
    return {"session_id": session_id, "record_id": record_id, "status": "recorded", "model_called": False}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8011, access_log=False, proxy_headers=False)
