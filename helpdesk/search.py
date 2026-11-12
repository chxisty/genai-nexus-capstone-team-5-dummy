"""Lightweight BM25 retrieval with exact-code and date-aware ranking."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from helpdesk.documents import DocumentChunk


_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could",
    "details", "do", "does", "find", "for", "from", "give", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "please", "railway",
    "railways", "show", "tell", "the", "there", "this", "to", "train",
    "trains", "what", "when", "where", "which", "who", "with", "would",
    "name", "information", "about", "ticket", "tickets", "rule", "rules",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


@dataclass(frozen=True)
class SearchHit:
    chunk: DocumentChunk
    score: float


class BM25Search:
    """In-memory BM25 index suitable for the small supplied document pack."""

    def __init__(self, chunks: Iterable[DocumentChunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(chunk.text) for chunk in self.chunks]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        self.term_frequencies = [Counter(tokens) for tokens in self.tokens]
        self.document_frequency: Counter[str] = Counter()
        for terms in self.term_frequencies:
            self.document_frequency.update(terms.keys())

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks:
            return []

        query_terms = set(query_tokens) - _STOPWORDS
        if not query_terms:
            return []
        query_phrase = " ".join(token for token in query_tokens if token not in _STOPWORDS)
        hits: list[SearchHit] = []
        count = len(self.chunks)
        for index, (chunk, terms, frequencies, length) in enumerate(
            zip(self.chunks, self.tokens, self.term_frequencies, self.lengths)
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency[term]
                inverse = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / max(self.average_length, 1.0)
                )
                score += inverse * frequency * (self.k1 + 1.0) / denominator

            normalized_text = " ".join(terms)
            if query_phrase and len(query_phrase) > 3 and query_phrase in normalized_text:
                score += 2.5

            # Train numbers, rule numbers, and station codes carry high signal.
            exact_tokens = [token for token in query_terms if any(char.isdigit() for char in token)]
            for token in exact_tokens:
                if token in terms:
                    score += 3.0

            # In near-ties, prefer newer source documents while retaining relevance.
            if score and chunk.date:
                score += min(int(chunk.date[:4]) - 2015, 15) * 0.002
            if score > 0:
                hits.append(SearchHit(chunk=chunk, score=score))

        hits.sort(key=lambda hit: (hit.score, hit.chunk.date or "", -hit.chunk.chunk), reverse=True)
        return hits[:max(1, limit)]
