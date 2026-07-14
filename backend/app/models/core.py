from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str               # "user" | "assistant"
    content: str
    citations: list[dict] = Field(default_factory=list)


class QueryAnalysis(BaseModel):
    query_type: str         # "factual" | "howto" | "news" | "comparison" | "code" | "direct"
    needs_web: bool
    sub_queries: list[str]  # 1-3 specific search queries
    is_temporal: bool       # "latest", "current", "2024", etc.


class SearchHit(BaseModel):
    url: str
    title: str
    snippet: str
    engine: str = ""
    score: float = 0.0


class PageExtract(BaseModel):
    url: str
    title: str
    relevant_text: str      # max 1500 chars of relevant content
    key_facts: list[str]    # 3-5 bullet point facts
    relevance_score: float  # 0-10


class Citation(BaseModel):
    index: int
    url: str
    title: str
    snippet: str = ""
