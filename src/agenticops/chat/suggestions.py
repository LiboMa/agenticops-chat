"""Suggestion-chips marker parsing (MVP-2.0.1 sub-project B slice 1).

Main agent 被提示在每条回复末尾输出一行:
    <<SUGGEST>>["action 1", "action 2", "action 3"]
本模块从回复文本剥离该块。所有出口(Web 持久化、CLI、IM)共用。
"""

import json
import re

SUGGEST_MARKER = "<<SUGGEST>>"

# 剥离时整行移除(标记行内的任何残余不落库)
_MARKER_LINE_RE = re.compile(r"^[ \t]*" + re.escape(SUGGEST_MARKER) + r".*$", re.MULTILINE)

_MAX_ITEMS = 3
_MAX_LEN = 60


def extract_suggestions(text: str) -> tuple[str, list[str]]:
    """从回复文本剥离 <<SUGGEST>>[...] 块。

    Returns:
        (clean_text, suggestions)。无标记 → (原文, [])。解析失败 →
        (标记行整行移除后的文本, [])。只认最后一次出现的标记;每条
        strip 后 ≤60 字符截断;最多 3 条;空串丢弃。
    """
    if not text or SUGGEST_MARKER not in text:
        return text, []

    idx = text.rfind(SUGGEST_MARKER)
    payload = text[idx + len(SUGGEST_MARKER):].strip()

    suggestions: list[str] = []
    try:
        # raw_decode 容忍数组后的尾随杂质
        arr, _ = json.JSONDecoder().raw_decode(payload)
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, str):
                    s = item.strip()
                    if s:
                        suggestions.append(s[:_MAX_LEN])
                if len(suggestions) >= _MAX_ITEMS:
                    break
    except (ValueError, TypeError):
        suggestions = []

    clean = _MARKER_LINE_RE.sub("", text).rstrip()
    return clean, suggestions
