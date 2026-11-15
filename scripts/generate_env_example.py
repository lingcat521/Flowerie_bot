"""Regenerate .env_example with python -m scripts.generate_env_example."""
from pathlib import Path

from src.config import Settings
from src.services.env_template import default_env_text

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / ".env_example"
    target.write_bytes(default_env_text(Settings).encode("utf-8"))
