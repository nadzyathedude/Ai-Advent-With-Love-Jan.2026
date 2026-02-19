"""Docs search tool with embedded BM25 keyword search — pure Python, zero external deps."""

import math
import os
import re
from pathlib import Path
from typing import Dict, List

from core.registry.tool_registry import Tool, ToolResult


class BM25Index:
    """Simple BM25 index over text chunks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: List[Dict] = []  # [{text, source_path, tokens}]
        self._avgdl: float = 0.0
        self._idf: Dict[str, float] = {}

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-zA-Z0-9_]+", text.lower())

    def add_document(self, text: str, source_path: str) -> None:
        tokens = self._tokenize(text)
        self._docs.append({
            "text": text,
            "source_path": source_path,
            "tokens": tokens,
        })

    def build(self) -> None:
        """Compute IDF and average document length."""
        n = len(self._docs)
        if n == 0:
            return
        self._avgdl = sum(len(d["tokens"]) for d in self._docs) / n
        # Count document frequency for each term
        df: Dict[str, int] = {}
        for doc in self._docs:
            seen = set(doc["tokens"])
            for token in seen:
                df[token] = df.get(token, 0) + 1
        # IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        for term, freq in df.items():
            self._idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """Return top-k results as [{text, source_path, score}]."""
        query_tokens = self._tokenize(query)
        scores = []
        for doc in self._docs:
            score = 0.0
            dl = len(doc["tokens"])
            # Build term frequency map
            tf_map: Dict[str, int] = {}
            for t in doc["tokens"]:
                tf_map[t] = tf_map.get(t, 0) + 1
            for qt in query_tokens:
                if qt not in self._idf:
                    continue
                tf = tf_map.get(qt, 0)
                idf = self._idf[qt]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * numerator / denominator
            scores.append({
                "text": doc["text"],
                "source_path": doc["source_path"],
                "score": round(score, 4),
            })
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]


class DocsSearchTool(Tool):
    """Searches project documentation using BM25 keyword search."""

    def __init__(self):
        self._index = BM25Index()
        self._indexed = False

    @property
    def name(self) -> str:
        return "docs.search_project_docs"

    @property
    def description(self) -> str:
        return "Search project docs using BM25 keyword matching. Returns top-k relevant chunks."

    @property
    def required_permissions(self) -> List[str]:
        return ["docs:read"]

    def _build_index(self) -> None:
        """Scan README.md and project/docs/*.md, chunk by double-newline."""
        base = Path(__file__).resolve().parents[2]
        doc_paths = []
        readme = base / "README.md"
        if readme.exists():
            doc_paths.append(readme)
        docs_dir = base / "project" / "docs"
        if docs_dir.exists():
            doc_paths.extend(sorted(docs_dir.glob("*.md")))
        faq_dir = base / "project" / "faq"
        if faq_dir.exists():
            doc_paths.extend(sorted(faq_dir.glob("*.md")))

        for path in doc_paths:
            text = path.read_text(encoding="utf-8")
            chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
            rel_path = str(path.relative_to(base))
            for chunk in chunks:
                self._index.add_document(chunk, rel_path)

        self._index.build()
        self._indexed = True

    def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        top_k = kwargs.get("top_k", 3)
        if not query:
            return ToolResult(success=False, error="Missing required argument: query")
        if not self._indexed:
            self._build_index()
        results = self._index.search(query, top_k=top_k)
        return ToolResult(success=True, data=results)
