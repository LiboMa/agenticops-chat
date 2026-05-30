"""AgenticOps Web API routers — mechanically split from app.py (no logic change).

Each router is an APIRouter included by app.py via app.include_router(). Routers
import schemas from web.schemas and helpers from web.helpers (dependency leaves);
they never import app.py (avoids an app<->router cycle). Singletons (_chat_sessions,
_executor_service, _im_sessions) are reached via request.app.state when needed.
"""
