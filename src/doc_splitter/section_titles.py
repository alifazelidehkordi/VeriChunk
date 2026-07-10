"""Generic section-title helpers and analysis-field validation."""

from __future__ import annotations

import re

from doc_splitter.ir.models import DocumentIR, Element

GENERIC_SKIP_TITLES = {
    "this page intentionally left blank",
    "intentionally left blank",
    "blank page",
}

SECTION_TITLE_RE = re.compile(r"^[A-Z][A-Z0-9 ,–\-/&()']{11,}$")
TITLE_MARKUP_RE = re.compile(r"\*\*|__|</?u>|</?mark>")
HTML_TAG_RE = re.compile(r"<[^>]+>")
BOLD_ONLY_RE = re.compile(r"^\*\*(.+)\*\*$")
URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)

TOPIC_MAX_WORDS = 14
TOPIC_MAX_CHARS = 100
TOPIC_PICK_MAX_CHARS = 90
FOCUS_MIN_CHARS = 30


def normalize_title_text(text: str) -> str:
    t = HTML_TAG_RE.sub("", text)
    t = TITLE_MARKUP_RE.sub("", t)
    return " ".join(t.split()).strip()


def _upper_ratio(text: str) -> float:
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for c in alpha if c.isupper()) / len(alpha)


def _has_case(text: str) -> bool:
    return any(c.islower() or c.isupper() for c in text if c.isalpha())


def _starts_like_title(text: str) -> bool:
    for c in text:
        if c.isalpha():
            return not _has_case(text) or c.isupper()
    return False


def _title_word_ratio(text: str) -> float:
    words = [w.strip("()[]{}:;,.!?؟،") for w in text.split()]
    words = [w for w in words if any(c.isalpha() for c in w)]
    cased = [w for w in words if _has_case(w)]
    if not cased:
        return 0.0
    title_words = [w for w in cased if w[0].isupper()]
    return len(title_words) / len(cased)


def _is_generic_skip_title(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered in GENERIC_SKIP_TITLES


def looks_like_section_title(text: str) -> bool:
    raw = text.strip()
    bold = BOLD_ONLY_RE.match(raw)
    if bold:
        raw = bold.group(1).strip()
    t = normalize_title_text(raw)
    if not t or _is_generic_skip_title(t):
        return False
    if URL_RE.match(t):
        return False
    if t.startswith(("•", "-", "*")):
        return False
    if _has_case(t) and t[0].islower():
        return False
    if len(t.split()) == 1 and len(t) < 20:
        return False
    if len(t) < 12 or len(t) > 140:
        return False
    if "=" in t:
        return False
    if re.search(r"\d", t) and len(t) < 40:
        return False
    ratio = _upper_ratio(t)
    if t.endswith(":") and ratio < 0.7:
        return False
    if t.endswith((".", ";", "?")) and ratio < 0.7:
        return False
    if t.endswith(("؟", "!", "؛")):
        return False
    title_ratio = _title_word_ratio(t)
    if " – " in t or " - " in t:
        return ratio >= 0.55 or title_ratio >= 0.55 or not _has_case(t)
    if SECTION_TITLE_RE.match(t):
        return True
    words = t.split()
    if len(words) <= 12 and _starts_like_title(t):
        if ratio >= 0.65 or title_ratio >= 0.65 or not _has_case(t):
            return True
    return False


def looks_like_body_sentence(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if len(t.split()) > TOPIC_MAX_WORDS:
        return True
    if t.endswith((".", ";", "?", "!")):
        return True
    if t[0].islower():
        return True
    if "," in t and len(t) > 60:
        return True
    return False


def _clean_title_candidate(text: str) -> str | None:
    raw = text.strip()
    bold = BOLD_ONLY_RE.match(raw)
    if bold:
        raw = bold.group(1).strip()
    cleaned = normalize_title_text(raw)
    if not cleaned or _is_generic_skip_title(cleaned):
        return None
    return cleaned


def _heading_text(el: Element) -> str | None:
    if el.type != "heading" or not el.text.strip():
        return None
    cleaned = _clean_title_candidate(el.text)
    if not cleaned:
        return None
    if len(cleaned) > 140:
        return None
    if looks_like_body_sentence(cleaned) and len(cleaned) > 80:
        return None
    return cleaned


def _paragraph_section_text(el: Element) -> str | None:
    if el.type != "paragraph" or not el.text.strip():
        return None
    text = el.text.strip()
    if looks_like_section_title(text):
        return _clean_title_candidate(text)
    return None


def _section_title_score(text: str, *, styled_heading: bool) -> int:
    cleaned = normalize_title_text(text)
    if _is_generic_skip_title(cleaned):
        return -1
    if styled_heading:
        score = 40
    elif looks_like_section_title(text):
        score = 30
    else:
        return -1
    score += int(_upper_ratio(text) * 30)
    score += int(_title_word_ratio(text) * 20)
    score += min(len(text) // 4, 20)
    if " – " in text or " - " in text:
        score += 10
    return score


def list_section_headings(ir: DocumentIR, start_idx: int, end_idx: int) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for el in ir.elements[start_idx : end_idx + 1]:
        candidates: list[tuple[str, bool]] = []
        heading = _heading_text(el)
        if heading:
            candidates.append((heading, True))
        elif el.type == "paragraph":
            text = _paragraph_section_text(el)
            if text:
                candidates.append((text, False))
        for text, styled in candidates:
            if text in seen:
                continue
            if _section_title_score(text, styled_heading=styled) < 0:
                continue
            headings.append(text)
            seen.add(text)
    return headings


def infer_chunk_topic(ir: DocumentIR, start_idx: int, end_idx: int) -> str:
    best = ""
    best_score = -1
    for el in ir.elements[start_idx : end_idx + 1]:
        candidates: list[tuple[str, bool]] = []
        heading = _heading_text(el)
        if heading:
            candidates.append((heading, True))
        elif el.type == "paragraph":
            text = _paragraph_section_text(el)
            if text:
                candidates.append((text, False))
        for text, styled in candidates:
            score = _section_title_score(text, styled_heading=styled)
            if score > best_score:
                best_score = score
                best = text
    return best


def pick_best_topic(
    headings: list[str],
    *,
    max_chars: int = TOPIC_PICK_MAX_CHARS,
) -> str:
    best = ""
    best_score = -1
    for order, heading in enumerate(headings):
        cleaned = normalize_title_text(heading)
        if not cleaned or len(cleaned) > max_chars:
            continue
        if looks_like_body_sentence(cleaned):
            continue
        score = _section_title_score(heading, styled_heading=False)
        if score < 0:
            continue
        score += max(0, 10 - order)
        if score > best_score:
            best_score = score
            best = cleaned
    return best


def validate_topic(text: str, *, field: str = "topic") -> None:
    t = normalize_title_text(text)
    if not t:
        raise ValueError(f"{field} must not be empty.")
    if len(t) > TOPIC_MAX_CHARS:
        raise ValueError(
            f"{field} is too long ({len(t)} chars). Use a short section title, not a sentence."
        )
    if len(t.split()) > TOPIC_MAX_WORDS:
        raise ValueError(
            f"{field} has too many words. Use a concise section title (max {TOPIC_MAX_WORDS} words)."
        )
    if looks_like_body_sentence(t):
        raise ValueError(
            f"{field} looks like a body sentence, not a section title. "
            "Use a concise agent-authored session title based on the whole chunk."
        )


def validate_study_focus(topic: str, focus: str, *, field: str = "study_focus") -> None:
    f = focus.strip()
    if len(f) < FOCUS_MIN_CHARS:
        raise ValueError(
            f"{field} is too short. Write 1–2 educational lines listing key concepts to study."
        )
    if f.strip().lower() == topic.strip().lower():
        raise ValueError(f"{field} must not duplicate the topic verbatim.")
    if topic.strip().lower() in f.strip().lower() and len(f) < len(topic) * 1.5:
        raise ValueError(
            f"{field} must expand on the topic with study concepts, not repeat the title."
        )


def validate_analysis(
    *,
    topic_fa: str,
    topic_en: str,
    study_focus_fa: str,
    study_focus_en: str,
) -> None:
    validate_topic(topic_en, field="topic_en")
    validate_topic(topic_fa, field="topic_fa")
    validate_study_focus(topic_en, study_focus_en, field="study_focus_en")
    validate_study_focus(topic_fa, study_focus_fa, field="study_focus_fa")


_RE_AUTO_REASON = re.compile(r"^auto", re.IGNORECASE)
_RE_AUTO_CUT = re.compile(r"auto-cut\s*~?\d*\s*words?", re.IGNORECASE)
_RE_AUTO_HEADINGS = re.compile(
    r"auto\s+.*(?:section[_ ]?headings?|from\s+section|headings)", re.IGNORECASE
)
_RE_EMPTY_PUNCT = re.compile(r"^[\s,;:.!?؟،]*$")


def validate_boundary_reason(reason: str) -> None:
    if not reason or not reason.strip():
        raise ValueError(
            "Boundary reason must not be empty. Explain the conceptual decision — "
            "where does the current topic end and a new one begin?"
        )
    r = reason.strip()
    if _RE_EMPTY_PUNCT.match(r):
        raise ValueError("Boundary reason must consist of actual words, not just punctuation.")
    if _RE_AUTO_CUT.match(r):
        raise ValueError(
            "Boundary reason must be a conceptual decision, not an auto-cut. "
            "Read the content window and explain WHY you chose this cut point."
        )
    if _RE_AUTO_REASON.match(r):
        raise ValueError(
            "Boundary reason must be written by the host agent, not auto-generated. "
            "Read the content and provide a specific conceptual reason."
        )
    if len(r) < 12:
        raise ValueError(
            f"Boundary reason is too short ({len(r)} chars). "
            "Provide a conceptual explanation (where the topic ends, why this cut is logical)."
        )


def validate_analysis_reason(reason: str) -> None:
    if not reason or not reason.strip():
        raise ValueError("Analysis reason must not be empty. Explain your coherence judgment.")
    r = reason.strip()
    if _RE_EMPTY_PUNCT.match(r):
        raise ValueError("Analysis reason must consist of actual words, not just punctuation.")
    if (
        _RE_AUTO_HEADINGS.match(r)
        or _RE_AUTO_CUT.match(r)
        or "auto from section" in r.lower()
        or "auto populated" in r.lower()
    ):
        raise ValueError(
            "Analysis reason must be written by the host agent. "
            "'auto from section_headings' is not acceptable — read the chunk and provide a real assessment."
        )
    if _RE_AUTO_REASON.match(r):
        raise ValueError(
            "Analysis reason must be written by the host agent, not auto-generated. "
            "Read the chunk content and provide a specific coherence judgment."
        )
    if len(r) < 8:
        raise ValueError(
            f"Analysis reason is too short ({len(r)} chars). "
            "Provide a real coherence assessment for this chunk."
        )
