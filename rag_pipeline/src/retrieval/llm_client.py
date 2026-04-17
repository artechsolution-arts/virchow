import re
import httpx
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import cfg

logger = logging.getLogger(__name__)

# For single-source: factual answer from one document
_SINGLE_PROMPT = (
    "You are a helpful document assistant. "
    "Answer the question based on the document text below. "
    "If conversation history is provided, use it to understand the context and what 'it', 'this', 'the document' refer to. "
    "Be concise and direct. Quote or paraphrase relevant parts from the text. "
    "If the document truly does not contain relevant information, say: 'Not found in this document.' "
)

# For multi-source per-file call: strict extraction only
_EXTRACT_PROMPT = (
    "You are a document assistant. "
    "Find the relevant information in the document below that answers the question. "
    "Be concise (2-4 sentences). Quote or paraphrase from the text. "
    "If the document does not contain relevant information, write exactly: 'Not found.' "
)

_NOT_FOUND_MARKERS = (
    "not found", "cannot answer", "no information", "does not contain",
    "not provided", "no mention", "not mentioned", "not available",
    "not present", "not specified", "not stated", "document does not",
)

# Max characters of context sent per file to the LLM
_MAX_CONTEXT_CHARS = 4000

# Max chars of history to prepend
_MAX_HISTORY_CHARS = 600


def _is_not_found(text: str) -> bool:
    t = text.lower().strip()
    return any(m in t for m in _NOT_FOUND_MARKERS) and len(t) < 250


def _clean_chunk(text: str) -> str:
    """Strip HTML tags, base64 image blobs, and excess whitespace from chunk text."""
    text = re.sub(r'!\[.*?\]\(data:[^)]{20,}\)', '[image]', text)
    text = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]{20,}', '[image]', text)
    text = re.sub(r'<td[^>]*>', ' | ', text, flags=re.IGNORECASE)
    text = re.sub(r'<th[^>]*>', ' | ', text, flags=re.IGNORECASE)
    text = re.sub(r'<tr[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _format_history(history: list) -> str:
    """Format recent conversation turns for inclusion in the prompt."""
    if not history:
        return ""
    lines = []
    for m in history:
        role = "User" if m["role"] == "user" else "Assistant"
        # Truncate long assistant answers (they contain doc text)
        content = m["content"][:200].replace("\n", " ")
        lines.append(f"{role}: {content}")
    text = "\n".join(lines)
    return text[:_MAX_HISTORY_CHARS]


def _call_ollama(prompt: str, num_predict: int) -> str:
    response = httpx.post(
        f"{cfg.llm_url}/api/generate",
        json={
            "model": cfg.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
                "top_p": 1.0,
                "repeat_penalty": 1.1,
            },
        },
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


def _extract_for_file(question: str, file_name: str, chunks: list,
                      history_text: str = "") -> tuple:
    """Return (file_name, extracted_answer) for a single document."""
    cleaned = [_clean_chunk(c) for c in chunks]
    context = "\n\n".join(cleaned)[:_MAX_CONTEXT_CHARS]
    history_section = f"Conversation so far:\n{history_text}\n\n" if history_text else ""
    prompt = (
        f"{_EXTRACT_PROMPT}\n\n"
        f"{history_section}"
        f"Document: {file_name}\n"
        f"Text:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer (copy from document text only):"
    )
    try:
        answer = _call_ollama(prompt, num_predict=200)
        return (file_name, answer)
    except Exception as e:
        logger.error(f"LLM extract failed for {file_name}: {e}")
        return (file_name, "Not found.")


def call_llm(question: str, context_chunks: list, history: list = None) -> tuple:
    """
    Returns (answer_text, relevant_file_names).
    history: recent chat messages [{role, content}] for conversation continuity.
    """
    history_text = _format_history(history) if history else ""

    # Group chunks by source file (keyword hits first since they're already ordered that way)
    by_file: dict = defaultdict(list)
    for c in context_chunks:
        by_file[c["file_name"]].append(c["chunk_text"])

    unique_files = list(by_file.keys())

    # ── Single source ─────────────────────────────────────────────────────────
    if len(unique_files) == 1:
        fname = unique_files[0]
        cleaned = [_clean_chunk(t) for t in by_file[fname]]
        context = "\n\n".join(cleaned)[:_MAX_CONTEXT_CHARS]
        history_section = f"Conversation so far:\n{history_text}\n\n" if history_text else ""
        prompt = (
            f"{_SINGLE_PROMPT}\n\n"
            f"{history_section}"
            f"Document: {fname}\n"
            f"Text:\n{context}\n\n"
            f"Question: {question}\n\nAnswer:"
        )
        try:
            answer = _call_ollama(prompt, num_predict=cfg.max_tokens)
            if _is_not_found(answer):
                return ("No relevant information found in the retrieved document.", set())
            # Prefix with filename so conversation history tracking can find the active doc
            return (f"**{fname}**\n{answer}", {fname})
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ("I was unable to generate a response at this time.", set())

    # ── Multiple sources: parallel extraction per file ─────────────────────────
    results: dict = {}
    max_workers = min(len(unique_files), 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_extract_for_file, question, fname, chunks, history_text): fname
            for fname, chunks in by_file.items()
        }
        for future in as_completed(futures):
            try:
                fname, answer = future.result()
                results[fname] = answer
            except Exception as e:
                logger.error(f"Future failed: {e}")

    # Build per-file formatted answer; skip files with no relevant content
    lines = []
    relevant_files: set = set()
    for fname in unique_files:
        ans = results.get(fname, "Not found.")
        if _is_not_found(ans):
            continue
        lines.append(f"**{fname}**\n{ans}")
        relevant_files.add(fname)

    if not lines:
        return ("No relevant information found across the retrieved documents.", set())

    return ("\n\n".join(lines), relevant_files)
