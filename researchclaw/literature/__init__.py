"""Real literature search and citation management for ResearchClaw.

Provides API clients for Semantic Scholar and arXiv, plus unified search
with deduplication and BibTeX generation.  All network I/O uses stdlib
``urllib`` — **zero** extra pip dependencies.
"""

from researchclaw.literature.models import Author, Paper
from researchclaw.literature.search import search_papers

__all__ = [
    "Author",
    "Paper",
    "search_papers",
]
