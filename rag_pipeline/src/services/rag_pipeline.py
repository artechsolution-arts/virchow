import os
import re
import logging
from src.config import cfg
from src.database.postgres_db import RBACManager
from src.ingestion.embedding.embedder import MxbaiEmbedder
from src.retrieval.llm_client import call_llm

logger = logging.getLogger(__name__)

# Matches document IDs like DEC-U2-PUR-24-25-40, INV-2024-001, PO-23-456, etc.
_DOC_ID_RE = re.compile(r'\b([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+){2,})\b')

# Matches file extensions to strip before doc-ID matching
_FILE_EXT_RE = re.compile(r'\.(pdf|xlsx?|docx?|csv|txt)$', re.IGNORECASE)

# Matches bare filenames with extensions (e.g. "report.pdf", "FEB-U2-DN.pdf")
_FILENAME_RE = re.compile(r'\S+\.(?:pdf|xlsx?|docx?|csv|txt)', re.IGNORECASE)

# Short conversational inputs that don't need RAG
_CONVERSATIONAL_RE = re.compile(
    r'^\s*(hello|hi+|hey|thanks|thank\s+you|ok(ay)?|sure|bye|goodbye|'
    r'good\s+(morning|afternoon|evening|day)|how\s+are\s+you|'
    r'what\s+can\s+you\s+do|help\s+me|who\s+are\s+you)\s*[.!?]?\s*$',
    re.IGNORECASE,
)

# Extracts filenames cited in assistant messages like **FEB-U2-DN.pdf**
_CITED_FILE_RE = re.compile(
    r'\*\*([^*]+\.(?:pdf|xlsx?|docx?|csv|txt))\*\*',
    re.IGNORECASE,
)

_STOP_WORDS = {
    # Common English function words
    "a", "an", "the", "in", "on", "at", "of", "for", "to", "and", "or", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "but", "not", "with", "this", "that", "from", "by", "what",
    "who", "which", "how", "when", "where", "me", "my", "we", "our", "its",
    "these", "those", "they", "them", "their", "there", "here", "will",
    "would", "could", "should", "shall", "may", "might", "can", "just", "also",
    "some", "any", "all", "each", "every", "both", "more", "most", "other",
    "than", "then", "now", "only", "over", "such", "very", "show", "give",
    "tell", "find", "list", "need", "want", "make", "like", "know", "about",
    "please", "full", "complete",
    # Ultra-common invoice/document words that appear in almost every doc
    "price", "prices", "amount", "amounts", "total", "totals", "invoice",
    "number", "details", "detail", "company", "purchase", "order", "orders",
    "quantity", "unit", "units", "rate", "rates", "value", "values",
    "payment", "payments", "information", "document", "documents",
    "product", "products", "items", "goods", "service", "services",
    "account", "accounts", "supply", "supplier", "buyer", "seller",
    "india", "limited", "private", "pvt", "ltd",
}

# Max chunks sent to LLM (prevent context overflow)
_MAX_LLM_CHUNKS = 10

# How many recent messages to consider for conversation context
_HISTORY_WINDOW = 6


class RetrievalService:
    def __init__(self, pool):
        self.rbac = RBACManager(pool)
        self.embedder = MxbaiEmbedder()
        logger.info("RetrievalService ready.")

    def _get_seaweedfs_url(self, file_path: str) -> str:
        basename = os.path.basename(file_path)
        uuid_part = basename[:36]
        filename = basename[37:]
        return f"{cfg.seaweedfs_filer_url}/buckets/{cfg.seaweedfs_bucket}/raw/{uuid_part}/{filename}"

    def _extract_doc_name(self, question: str) -> str | None:
        """Return the first document-ID-like token or filename found in the question, or None."""
        # First pass: look for bare filenames with extensions (e.g. "FEB-U2-DN.pdf")
        filename_match = _FILENAME_RE.search(question)
        if filename_match:
            return filename_match.group(0).strip('.,;:?!()[]"\'')

        # Second pass: look for doc IDs, stripping extensions first (e.g. "DEC-U2-PUR-24-25-40")
        for token in question.split():
            clean = token.strip('.,;:?!()[]"\'')
            # Strip file extension if present before matching
            name_only = _FILE_EXT_RE.sub('', clean)
            if _DOC_ID_RE.fullmatch(name_only):
                return clean  # return with extension so DB ILIKE can still match
            if _DOC_ID_RE.fullmatch(clean):
                return clean
        return None

    def _extract_keywords(self, question: str) -> list:
        """Return content words (>=5 chars, not stop words) for keyword search.
        Treats hyphens as separators to handle tokens like 'expences-dome'."""
        words = re.sub(r'[^\w\s]', ' ', question.lower()).split()
        return [w for w in words if len(w) >= 5 and w not in _STOP_WORDS]

    def _extract_active_files(self, history: list) -> list:
        """Return filenames cited in the most recent assistant message that had citations.
        These are the 'active' documents for this conversation thread."""
        for msg in reversed(history[-_HISTORY_WINDOW:]):
            if msg["role"] == "assistant":
                found = _CITED_FILE_RE.findall(msg["content"])
                if found:
                    # Deduplicate preserving order
                    seen: dict = {}
                    for f in found:
                        seen[f] = True
                    logger.info(f"Active documents from history: {list(seen.keys())}")
                    return list(seen.keys())
        return []

    def query(self, question: str, user_id: str, dept_id: str, chat_id: str = None) -> dict:
        # 1. Short-circuit for conversational inputs — no RAG needed
        if _CONVERSATIONAL_RE.match(question):
            logger.info("Conversational query detected — skipping RAG")
            if not chat_id:
                chat_id = self.rbac.create_chat(user_id, dept_id, title=question[:60])
            self.rbac.update_chat_title_if_empty(chat_id, question[:60])
            self.rbac.add_message(chat_id, "user", question)
            answer = (
                "Hello! I'm Virchow, your document knowledge assistant. "
                "Ask me anything about your uploaded documents — prices, suppliers, quantities, and more."
            )
            self.rbac.add_message(chat_id, "assistant", answer)
            return {"answer": answer, "citations": [], "chat_id": chat_id}

        # 2. Fetch conversation history (for context continuity)
        history: list = []
        active_files: list = []
        if chat_id:
            history = self.rbac.get_messages_full(chat_id, dept_id)
            active_files = self._extract_active_files(history)

        # 3. Embed the question
        query_vec = self.embedder.embed_text(question)

        # 4a. Document-aware vector retrieval
        #     Priority: explicit doc ID in question > active files from history > global
        doc_name = self._extract_doc_name(question)
        if doc_name:
            logger.info(f"Detected document ID {doc_name!r} — filtered vector search")
            vec_results = self.rbac.vector_search_by_filename(
                query_vec, dept_id, doc_name, top_k=cfg.top_k_retrieval
            )
            if not vec_results:
                logger.info(f"No chunks for {doc_name!r}, falling back to global search")
                vec_results = self.rbac.vector_search(query_vec, dept_id, top_k=cfg.top_k_retrieval)
            # Clear active_files so we don't re-inject old context
            active_files = []

        elif active_files:
            # No explicit doc mentioned — search ONLY the active document(s).
            # Never fall back to global search here; that causes cross-document contamination.
            logger.info(f"Continuing conversation on {active_files} — scoped vector search (no global fallback)")
            vec_results = []
            seen_ids: set = set()
            for fname in active_files[:2]:
                for r in self.rbac.vector_search_by_filename(
                    query_vec, dept_id, fname, top_k=cfg.top_k_retrieval
                ):
                    if r["chunk_id"] not in seen_ids:
                        vec_results.append(r)
                        seen_ids.add(r["chunk_id"])
        else:
            vec_results = self.rbac.vector_search(query_vec, dept_id, top_k=cfg.top_k_retrieval)

        # 4b. Keyword search — always scoped to the target document(s) to prevent contamination
        keywords = self._extract_keywords(question)
        kw_results: list = []
        if len(keywords) >= 2:
            if doc_name:
                # Explicit doc targeted — restrict keywords to that file only (ILIKE pattern)
                kw_results = self.rbac.keyword_search_by_filename_pattern(
                    keywords, dept_id, doc_name, top_k=cfg.top_k_retrieval
                )
            elif active_files:
                # Conversation context — restrict to active document(s), no global fallback
                kw_results = self.rbac.keyword_search_in_files(
                    keywords, dept_id, active_files, top_k=cfg.top_k_retrieval
                )
            else:
                # No document context — global keyword search is safe
                kw_results = self.rbac.keyword_search(keywords, dept_id, top_k=cfg.top_k_retrieval)
            logger.info(f"Keyword search ({keywords}) → {len(kw_results)} chunks")

        # 5. Merge: keyword hits first (exact-match priority), then vector hits not already seen
        seen_chunks = {r["chunk_id"] for r in kw_results}
        merged = list(kw_results)
        for r in vec_results:
            if r["chunk_id"] not in seen_chunks:
                merged.append(r)

        # 6. Threshold filter: keyword hits bypass threshold; vector-only hits must meet it
        results = [
            r for r in merged
            if r.get("_keyword_hit") or float(r["similarity"]) >= cfg.similarity_threshold
        ]

        # 7. Cap results to avoid overwhelming the LLM
        results = results[:_MAX_LLM_CHUNKS]

        if not results:
            no_ans = "I couldn't find relevant information in the knowledge base to answer your question."
            if not chat_id:
                chat_id = self.rbac.create_chat(user_id, dept_id, title=question[:60])
            self.rbac.update_chat_title_if_empty(chat_id, question[:60])
            self.rbac.add_message(chat_id, "user", question)
            self.rbac.add_message(chat_id, "assistant", no_ans)
            return {"answer": no_ans, "citations": [], "chat_id": chat_id}

        # 8. Call LLM — pass recent conversation history for context continuity
        recent_history = history[-_HISTORY_WINDOW:] if history else []
        answer, relevant_files = call_llm(question, results, history=recent_history)

        # 9. Build citations — only files the LLM found relevant
        citations = []
        if relevant_files:
            seen: dict = {}
            for r in results:
                doc_id = str(r["document_id"])
                fname = r["file_name"]
                if doc_id in seen or fname not in relevant_files:
                    continue
                seen[doc_id] = True
                seaweed_url = self._get_seaweedfs_url(r["file_path"])
                citations.append({"name": fname, "document_id": doc_id, "url": seaweed_url})

        # 10. Persist chat + messages
        if not chat_id:
            chat_id = self.rbac.create_chat(user_id, dept_id, title=question[:60])
        self.rbac.update_chat_title_if_empty(chat_id, question[:60])
        self.rbac.add_message(chat_id, "user", question)
        self.rbac.add_message(chat_id, "assistant", answer)
        self.rbac.log_retrieval(
            chat_id, user_id, dept_id, question,
            [str(r["chunk_id"]) for r in results],
            [float(r["similarity"]) for r in results],
        )

        return {"answer": answer, "citations": citations, "chat_id": chat_id}

    def get_chat_messages(self, chat_id: str, dept_id: str) -> list:
        return self.rbac.get_messages(chat_id, dept_id)

    def get_user_chats(self, user_id: str, dept_id: str) -> list:
        return self.rbac.get_user_chats(user_id, dept_id)
