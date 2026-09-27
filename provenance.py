"""总结溯源：把转录稿切为可验证的证据片段，并解析模型引用。"""
import json
import re


CITATION_RE = re.compile(r"【原文:((?:S\d{4,})(?:\s*[,，、]\s*S\d{4,})*)】")


def build_source_chunks(transcript: str, target_chars: int = 360) -> list[dict]:
    """按自然句边界切片，同时保留片段在完整转录稿中的真实位置。"""
    if not transcript:
        return []

    boundaries = list(re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?|\n", transcript))
    chunks = []
    start = None
    end = None

    def flush():
        nonlocal start, end
        if start is None or end is None:
            return
        raw = transcript[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing_end = len(raw.rstrip())
        real_start = start + leading
        real_end = start + trailing_end
        if real_end > real_start:
            chunks.append({
                "id": f"S{len(chunks) + 1:04d}",
                "start": real_start,
                "end": real_end,
                "text": transcript[real_start:real_end],
            })
        start = end = None

    for match in boundaries:
        token = match.group(0)
        if not token.strip():
            if start is not None and end - start >= target_chars // 2:
                flush()
            continue
        if start is None:
            start = match.start()
        end = match.end()
        # 某些 ASR 返回几乎不带标点的长段落，避免整段变成一个巨大证据块。
        while end - start >= target_chars * 2:
            cut = start + target_chars
            end_before_cut = end
            end = cut
            flush()
            start = cut
            end = end_before_cut
        if end - start >= target_chars:
            flush()
    flush()
    return chunks


def format_chunked_source(chunks: list[dict]) -> str:
    return "\n\n".join(f"[{item['id']}] {item['text']}" for item in chunks)


def extract_provenance(summary: str, chunks: list[dict]) -> str:
    """只保留指向既有片段的引用；证据文本始终取自真实转录稿。"""
    chunk_map = {item["id"]: item for item in chunks}
    citations = []
    seen = set()
    for match in CITATION_RE.finditer(summary or ""):
        marker = match.group(0)
        ids = re.findall(r"S\d{4,}", match.group(1))
        valid_ids = [source_id for source_id in ids if source_id in chunk_map]
        if not valid_ids or marker in seen:
            continue
        seen.add(marker)
        citations.append({
            "marker": marker,
            "sources": [chunk_map[source_id] for source_id in valid_ids],
        })
    return json.dumps({"version": 1, "citations": citations}, ensure_ascii=False)
