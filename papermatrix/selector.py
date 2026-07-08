from __future__ import annotations

import re


FIELD_KEYWORDS = {
    "problem": ["problem", "challenge", "task", "aim", "goal", "address", "motivation"],
    "method": ["method", "approach", "framework", "architecture", "model", "we propose", "we introduce", "algorithm"],
    "dataset": ["dataset", "datasets", "benchmark", "corpus", "data", "evaluation set"],
    "metric": ["metric", "metrics", "accuracy", "f1", "precision", "recall", "bleu", "rouge", "auc", "score"],
    "result": ["result", "results", "outperform", "improve", "improvement", "achieve", "performance", "state-of-the-art", "sota"],
    "limitation": ["limitation", "limitations", "future work", "fail", "failure", "weakness", "cannot", "does not", "discussion"],
}


def _is_references_chunk(chunk: dict) -> bool:
    text = str(chunk.get("text", "")).lstrip().lower()
    return bool(re.match(r"^(references|bibliography)\b", text))


def _position_bonus(field: str, position: float) -> float:
    if field == "problem":
        return 3.0 if position <= 0.25 else 0.0
    if field == "method":
        return 2.5 if 0.15 <= position <= 0.55 else 0.5 if position < 0.7 else 0.0
    if field in {"dataset", "metric", "result"}:
        return 2.5 if 0.35 <= position <= 0.85 else 0.5 if position > 0.2 else 0.0
    if field == "limitation":
        return 3.0 if position >= 0.66 else 0.0
    return 0.0


def _keyword_score(text: str, keywords: list[str]) -> float:
    score = 0.0
    for keyword in keywords:
        pattern = re.escape(keyword.lower())
        matches = re.findall(pattern, text)
        if matches:
            score += 2.0 + min(len(matches), 4)
    return score


def _score_chunk(chunk: dict, field: str, index: int, total: int) -> float:
    text = str(chunk.get("text", "")).lower()
    position = index / max(total - 1, 1)
    score = _keyword_score(text, FIELD_KEYWORDS[field])
    score += _position_bonus(field, position)
    if _is_references_chunk(chunk):
        score -= 100.0
    return score


def select_chunks_for_extraction(
    chunks: list[dict],
    top_k_per_field: int = 2,
    max_chunks: int = 12,
) -> list[dict]:
    if len(chunks) <= max_chunks:
        return chunks

    selected_indexes: set[int] = set(range(min(2, len(chunks))))
    total = len(chunks)

    for field in FIELD_KEYWORDS:
        ranked = sorted(
            range(total),
            key=lambda idx: (_score_chunk(chunks[idx], field, idx, total), -idx),
            reverse=True,
        )
        selected_indexes.update(ranked[:top_k_per_field])

    for index in range(total - 1, -1, -1):
        if not _is_references_chunk(chunks[index]):
            selected_indexes.add(index)
            break

    ordered_indexes = sorted(selected_indexes)
    if len(ordered_indexes) > max_chunks:
        must_keep = set(range(min(2, total)))
        last_non_ref = next((idx for idx in range(total - 1, -1, -1) if not _is_references_chunk(chunks[idx])), None)
        if last_non_ref is not None:
            must_keep.add(last_non_ref)

        scored = sorted(
            ordered_indexes,
            key=lambda idx: (
                idx in must_keep,
                max(_score_chunk(chunks[idx], field, idx, total) for field in FIELD_KEYWORDS),
            ),
            reverse=True,
        )
        ordered_indexes = sorted(scored[:max_chunks])

    return [chunks[index] for index in ordered_indexes]
