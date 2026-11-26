"""AgenticOps Web API routers — mechanically split from app.py (no logic change).

Each router is an APIRouter included by app.py via app.include_router(). Routers
import schemas from web.schemas and helpers from web.helpers (dependency leaves);
they never import app.py at module level (app imports them: a cycle). The process's
own objects that live in app.py (_chat_sessions, _executor_service, _allowed_model_ids
— tests patch them there by name) are imported from agenticops.web.app inside the
function that uses them.
"""
