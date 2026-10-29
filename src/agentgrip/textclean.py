"""Text normalisation and feature extraction.

Message text is read once inside an adapter, reduced to a few booleans and integers (Feat),
and then dropped. Neither the report nor the JSON export ever contains message text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Wrapper blocks that harnesses inject into the user turn: context, not the user's own words.
_WRAPPERS = (
    "in-app-browser-context", "system-reminder", "environment_context", "turn_aborted",
    "user_instructions", "ide_opened_file", "ide_selection", "command-name", "command-message",
    "command-args", "local-command-stdout", "local-command-caveat", "codex_apps_open_page",
    "external_codex_apps_open_page", "INSTRUCTIONS", "task-notification",
)
_WRAP_RE = re.compile(r"<(%s)\b[^>]*>.*?</\1>" % "|".join(re.escape(w) for w in _WRAPPERS), re.S)
_FILES_HDR = re.compile(r"^\s*# Files mentioned by the user:.*?## My request:\s*", re.S)
_APP_LINK = re.compile(r"\[\$?[^\]\n]{0,80}\]\((?:app|plugin)://[^)]*\)")


def strip_context(text: str) -> str:
    t = _FILES_HDR.sub("", text)
    t = _WRAP_RE.sub("", t)
    t = _APP_LINK.sub("", t)
    return t.strip()


_QUESTION = re.compile(
    r"[?？]|吗|为什么|怎么|如何|能不能|可不可以|是不是|是否|有没有"
    r"|^\s*(why|how|what|which|when|where|can you|could you|is there|are there|should i|do you)\b",
    re.I,
)
# strong cues count anywhere; weak negations only at the start of the message
_CORR_STRONG = re.compile(
    r"不对|错了|重来|撤销|回滚|别再|不要再|不行|不应该|有问题|不是这样|"
    r"\b(wrong|revert|undo|roll ?back|that'?s not|not what i)\b",
    re.I,
)
_CORR_WEAK = re.compile(r"^\s*(不是|没有|别|不要|no[,. ]|nope|don'?t|stop)", re.I)
_BARE = re.compile(
    r"^\s*(继续|好|好的|行|可以|ok|okay|yes|y|对|嗯|是|开始|做|执行|确认|同意|go|go ahead|continue|proceed|lgtm|sure)\s*[.!。！~ ]*$",
    re.I,
)
_CODEISH = re.compile(
    r"```|/Users/|/home/|[A-Za-z]:\\|\./|\.(py|ts|tsx|js|go|rs|java|kt|json|ya?ml|sh|md)\b|https?://|\bgit (status|diff|log|rebase|push|pull)\b"
)


@dataclass(frozen=True)
class Feat:
    chars: int
    question: bool
    correction: bool
    bare: bool
    codeish: bool


def features(text: str) -> Feat:
    t = text.strip()
    return Feat(
        chars=len(t),
        question=bool(_QUESTION.search(t)),
        correction=bool(_CORR_STRONG.search(t) or _CORR_WEAK.search(t)),
        bare=bool(_BARE.match(t)),
        codeish=bool(_CODEISH.search(t)),
    )


_SLASH = re.compile(r"^/[A-Za-z][\w:.-]*(\s|$)")


def is_slash_command(text: str) -> bool:
    t = text.strip()
    return bool(_SLASH.match(t)) and "/" not in t.split()[0][1:]


# Prefixes of messages injected by tooling rather than typed by the user.
DEFAULT_AUTO_PREFIXES = (
    r"Caveat:", r"<command-", r"<local-command", r"<system-reminder>", r"\[Request interrupted",
    r"<task-notification", r"Base directory for this skill:", r"<skill name=",
)
_AUTO = re.compile(r"^\s*(%s)" % "|".join(DEFAULT_AUTO_PREFIXES))


def auto_prefix(text: str) -> Optional[str]:
    m = _AUTO.match(text)
    return m.group(1) if m else None
