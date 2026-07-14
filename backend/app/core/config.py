from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Ollama
    ollama_host: str = "http://localhost:11434"
    planner_model: str = "phi3:mini"        # fast: routing, extraction, reasoning
    synthesizer_model: str = "llama3.1:8b"  # quality: final answer
    embed_model: str = "nomic-embed-text"

    # SearXNG
    searxng_url: str = "http://localhost:8080"
    searxng_results: int = 10               # results per search
    searxng_engines: str = "google,bing,wikipedia,duckduckgo"

    # ChromaDB
    chroma_path: str = "./chroma_db"
    cache_collection: str = "agent_cache"
    cache_ttl_seconds: int = 1800           # 30 min; 0 for temporal queries
    cache_similarity_threshold: float = 0.12

    # Scraper
    scraper_timeout_ms: int = 30_000
    scraper_min_delay_ms: int = 1500
    scraper_max_delay_ms: int = 3500
    scraper_headless: bool = False         # headed by default — watch the cursor surf live
    max_html_chars: int = 8000              # chars fed to content extractor LLM

    # ReAct loop
    max_iterations: int = 3                 # max search/scrape cycles
    max_scrape_per_iter: int = 3            # max parallel scrapes per iteration
    min_relevant_extracts: int = 2          # extracts needed before DONE allowed
    relevance_threshold: float = 5.0        # min score to count as relevant

    # Multi-agent orchestration
    max_researchers: int = 3                # parallel researcher agents fanned out per round
    max_critic_rounds: int = 1              # extra gap-filling rounds the critic may trigger
    max_concurrent_browsers: int = 2        # cap simultaneous headed Chrome windows across researchers

    # Context builder
    max_context_extracts: int = 5           # top-k extracts for synthesis
    max_context_chars: int = 6000           # total chars in synthesis context

    # Session
    session_max_turns: int = 8              # turns kept in history window
    session_max_sessions: int = 1000        # max in-memory sessions

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
