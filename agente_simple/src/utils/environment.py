from decouple import config

OPENAI_API_KEY: str = config("OPENAI_API_KEY", default="")
OPENAI_MODEL: str = config("OPENAI_MODEL", default="gpt-4o-mini")

LLM_PROVIDER: str = config("LLM_PROVIDER", default="openai")

OLLAMA_BASE_URL: str | None = config("OLLAMA_BASE_URL", default=None)
OLLAMA_MODEL: str | None = config("OLLAMA_MODEL", default=None)

DATABASE_URL: str = config("DATABASE_URL")
HISTORY_LIMIT: int = config("HISTORY_LIMIT", default=10, cast=int)

LANGFUSE_PUBLIC_KEY: str | None = config("LANGFUSE_PUBLIC_KEY", default=None)
LANGFUSE_SECRET_KEY: str | None = config("LANGFUSE_SECRET_KEY", default=None)
LANGFUSE_HOST: str | None = config("LANGFUSE_HOST", default=None)

LANGSMITH_API_KEY: str | None = config("LANGSMITH_API_KEY", default=None)
LANGSMITH_PROJECT: str | None = config("LANGSMITH_PROJECT", default=None)
LANGCHAIN_TRACING_V2: str | None = config("LANGCHAIN_TRACING_V2", default=None)
