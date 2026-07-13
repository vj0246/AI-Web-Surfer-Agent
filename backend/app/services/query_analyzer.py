import json
import re

import ollama

from app.core.config import settings
from app.models.core import QueryAnalysis

# Detected by fast regex — forces is_temporal=True
_TEMPORAL_PATTERNS = re.compile(
    r"\b(latest|current|now|today|2024|2025|2026|recent|new|just|trending|breaking|live)\b",
    re.IGNORECASE,
)

# These topic keywords ALWAYS require web search, no matter what the model says.
# The model regularly mislabels travel/price/event queries as "direct".
_FORCE_WEB_PATTERNS = re.compile(
    r"\b(flight|flights|ticket|tickets|fare|fares|airfare|airline|airlines|"
    r"price|prices|cost|costs|rate|rates|cheap|cheapest|best deal|deals|"
    r"hotel|hotels|booking|book|weather|forecast|stock|stocks|market|"
    r"score|scores|result|results|news|headline|headlines|schedule|timetable|"
    r"route|routes|train|trains|bus|buses|taxi|cab|"
    r"restaurant|menu|open|closed|hours|near me|nearby|location|"
    r"exchange rate|currency|bitcoin|crypto|"
    r"movie|showtimes|show time|release|"
    r"visa|passport|embassy|"
    r"salary|jobs|job|hiring|vacancy|"
    r"MakeMyTrip|Goibibo|Yatra|Skyscanner|Kayak|Expedia|"
    r"IndiGo|SpiceJet|Air India|Vistara|GoAir|Akasa)\b",
    re.IGNORECASE,
)

# Only these query types are allowed to skip web search
_DIRECT_ONLY_TYPES = {"code", "math", "greet"}

_ANALYZE_PROMPT = """You are a query classifier for a web-search agent. Classify the query below.

User query: "{query}"

Conversation history:
{history_text}

RULES:
1. needs_web=true for ANY query about: prices, flights, hotels, weather, news, current events,
   schedules, real people, real companies, sports scores, travel, jobs, restaurants, or anything
   requiring data from the internet. When in doubt → needs_web=true.
2. needs_web=false ONLY for: pure math ("2+2"), coding syntax ("how to write a for loop"),
   or simple greetings. NOT for flight prices, NOT for travel info, NOT for anything real-world.
3. sub_queries: write 1-3 specific search queries that will find the answer. Be concrete.
   For travel queries include origin, destination, date. For price queries include product + year.
4. is_temporal=true when the answer changes day-to-day (prices, news, schedules, weather).

query_type: "factual" | "howto" | "news" | "comparison" | "code" | "direct"
  direct = ONLY math / coding syntax / greetings — nothing else

Examples:
- "flight Mumbai Delhi July 30" → news, needs_web=true, is_temporal=true,
  ["cheapest flight Mumbai to Delhi July 30 2026", "IndiGo SpiceJet Mumbai Delhi July 30 price"]
- "cheapest airline ticket Mumbai Delhi" → news, needs_web=true, is_temporal=true,
  ["cheapest flight Mumbai to Delhi 2026", "budget airline Mumbai Delhi ticket price"]
- "what is 2+2" → direct, needs_web=false, []
- "how does RLHF work" → factual, needs_web=true, ["RLHF reinforcement learning from human feedback"]
- "latest iPhone 16 price India" → news, needs_web=true, is_temporal=true, ["iPhone 16 price India 2024"]
- "how to write a Python for loop" → code, needs_web=false, []

Return JSON only. No markdown, no explanation:
{{"query_type": "...", "needs_web": true, "sub_queries": ["..."], "is_temporal": false, "temporal_hint": null}}"""


async def analyze_query(query: str, history_text: str) -> QueryAnalysis:
    is_temporal_fast = bool(_TEMPORAL_PATTERNS.search(query))
    force_web = bool(_FORCE_WEB_PATTERNS.search(query)) or is_temporal_fast

    prompt = _ANALYZE_PROMPT.format(query=query, history_text=history_text or "None")

    client = ollama.AsyncClient(host=settings.ollama_host)
    response = await client.generate(model=settings.planner_model, prompt=prompt)
    raw = response["response"].strip()

    # strip markdown fences
    raw = re.sub(r"^```(?:json)?", "", raw).rstrip("`").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    raw = match.group() if match else raw

    try:
        data = json.loads(raw)
        model_needs_web = bool(data.get("needs_web", True))
        # Hard override: if force_web is set, ALWAYS search the web
        needs_web = model_needs_web or force_web
        is_temporal = bool(data.get("is_temporal", is_temporal_fast)) or is_temporal_fast

        sub_queries = [str(q) for q in data.get("sub_queries", [query])[:3]]
        # If no sub_queries but we need web, use the raw query
        if needs_web and not sub_queries:
            sub_queries = [query]

        analysis = QueryAnalysis(
            query_type=str(data.get("query_type", "factual")),
            needs_web=needs_web,
            sub_queries=sub_queries,
            is_temporal=is_temporal,
            temporal_hint=data.get("temporal_hint"),
        )
        print(f"[query_analyzer] query={query!r} type={analysis.query_type} "
              f"needs_web={analysis.needs_web} (model={model_needs_web}, force={force_web}) "
              f"sub_queries={analysis.sub_queries}")
        return analysis

    except (json.JSONDecodeError, KeyError):
        print(f"[query_analyzer] PARSE FAILED query={query!r}, raw={raw!r} -> fallback")
        return QueryAnalysis(
            query_type="factual",
            needs_web=True,
            sub_queries=[query],
            is_temporal=is_temporal_fast,
            temporal_hint=None,
        )
