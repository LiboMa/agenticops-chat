"""IM gateway module — bidirectional chat with Feishu/DingTalk/WeCom."""

from agenticops.im.gateway import IMGateway, IMInboundMessage

# Feishu WS requires lark_oapi — import lazily to avoid hard dependency
try:
    from agenticops.im.feishu_ws import FeishuWSService, start_feishu_ws, stop_feishu_ws
except ImportError:
    FeishuWSService = None  # type: ignore[assignment,misc]
    start_feishu_ws = None  # type: ignore[assignment]
    stop_feishu_ws = None  # type: ignore[assignment]

__all__ = [
    "IMGateway",
    "IMInboundMessage",
    "FeishuWSService",
    "start_feishu_ws",
    "stop_feishu_ws",
]
