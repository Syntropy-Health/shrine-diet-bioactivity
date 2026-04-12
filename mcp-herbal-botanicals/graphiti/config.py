"""
Configuration for Graphiti KG integration.

Connects to:
- Neo4j on Railway (or local Docker)
- Local embedding server (LM Studio) for zero-cost embeddings
- Local or cloud LLM for entity extraction

All values configurable via environment variables.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Neo4j connection
# Railway: bolt://neo4j-test-2be3.up.railway.app:7687
# Railway proxy: bolt://metro.proxy.rlwy.net:22971
# Local: bolt://localhost:7687
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://metro.proxy.rlwy.net:22971")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "demodemo")

# Embedding configuration (OpenAI-compatible endpoint)
# LM Studio on WSL2: must use the Windows host IP (gateway), not 127.0.0.1
# Auto-detect WSL2 host IP if not explicitly set
def _detect_lms_url() -> str:
    """Detect LM Studio URL, handling WSL2 → Windows host gateway."""
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            gateway = result.stdout.split()[2]
            return f"http://{gateway}:1234/v1"
    except Exception:
        pass
    return "http://127.0.0.1:1234/v1"

_default_lms_url = _detect_lms_url()
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", _default_lms_url)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m-qat")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "not-needed")

# LLM configuration (for Graphiti entity extraction)
# Can use local LM Studio or cloud API
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _default_lms_url)
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")

# SQLite database path (source data)
SQLITE_DB_PATH = os.getenv(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data_local", "herbal_botanicals.db"),
)

# Ingestion settings
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))
MAX_HERBS = int(os.getenv("MAX_HERBS", "100"))  # Start small for experiments
MAX_COMPOUNDS = int(os.getenv("MAX_COMPOUNDS", "500"))
MAX_LINKS = int(os.getenv("MAX_LINKS", "2000"))  # Cap relationship episodes


def validate_config() -> list[str]:
    """Check configuration and return list of warnings."""
    warnings = []
    if not NEO4J_PASSWORD:
        warnings.append("NEO4J_PASSWORD not set — connection will fail")
    if "127.0.0.1" in EMBEDDING_BASE_URL or "localhost" in EMBEDDING_BASE_URL:
        warnings.append(f"Using local embedding server at {EMBEDDING_BASE_URL} — ensure Ollama/LM Studio is running")
    if "127.0.0.1" in LLM_BASE_URL or "localhost" in LLM_BASE_URL:
        warnings.append(f"Using local LLM at {LLM_BASE_URL} — ensure Ollama/LM Studio is running with a chat model")
    return warnings
