import re


SECTION_PATTERNS = {
    "opening": r"\u3010\u5f00\u5934\u3011\s*(.*?)(?=\u3010\u4e2d\u95f4\u3011|\u3010\u7ed3\u5c3e\u3011|$)",
    "middle": r"\u3010\u4e2d\u95f4\u3011\s*(.*?)(?=\u3010\u7ed3\u5c3e\u3011|$)",
    "ending": r"\u3010\u7ed3\u5c3e\u3011\s*(.*?)$",
}


TITLE_PATTERN = re.compile(r"\u3010\u6807\u9898\u3011\s*(.+?)(?:\n|\u3010|$)", re.DOTALL)
BODY_LABEL = "\u3010\u6b63\u6587\u3011"
TITLE_LABEL = "\u3010\u6807\u9898\u3011"
SEGMENT_LABEL_RE = re.compile(r"\u3010(?:\u5f00\u5934|\u4e2d\u95f4|\u7ed3\u5c3e)\u3011\s*")


def extract_title(raw: str) -> str:
    match = TITLE_PATTERN.search(raw)
    return match.group(1).strip() if match else ""


def extract_segments(raw: str) -> dict:
    segments = {}
    for key, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, raw, re.DOTALL)
        if not match:
            continue
        value = match.group(1).strip().rstrip("\u3010\n")
        if value:
            segments[key] = value
    return segments


def parse_segmented_output(raw: str) -> tuple[str, dict, str]:
    title = extract_title(raw)
    segments = extract_segments(raw)
    if len(segments) == 3:
        article = "\n\n".join([segments["opening"], segments["middle"], segments["ending"]])
        return title, segments, article

    cleaned_raw = raw.replace(TITLE_LABEL, "", 1).strip()
    if BODY_LABEL in raw:
        article = raw.split(BODY_LABEL, 1)[1].strip()
    else:
        lines = cleaned_raw.split("\n")
        if not title:
            title = lines[0].lstrip("#").strip() if lines else ""
            article = "\n".join(lines[1:]).strip()
        else:
            article = cleaned_raw
    article = SEGMENT_LABEL_RE.sub("", article).strip()
    if title:
        article = re.sub(rf"^{re.escape(title)}\s*", "", article, count=1).strip()
    return title, {}, article


def join_segments(segments: dict) -> str:
    return "\n\n".join([
        segments.get("opening", ""),
        segments.get("middle", ""),
        segments.get("ending", ""),
    ]).strip()


def resplit_segments(article: str) -> dict:
    paragraphs = [paragraph for paragraph in article.split("\n\n") if paragraph.strip()]
    if len(paragraphs) < 3:
        return {"opening": "", "middle": article, "ending": ""}

    count = len(paragraphs)
    opening_size = max(1, count // 4)
    ending_size = max(1, count // 4)
    middle_size = count - opening_size - ending_size
    opening = "\n\n".join(paragraphs[:opening_size])
    middle = "\n\n".join(paragraphs[opening_size:opening_size + middle_size])
    ending = "\n\n".join(paragraphs[opening_size + middle_size:])
    return {"opening": opening, "middle": middle, "ending": ending}
