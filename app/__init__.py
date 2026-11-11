"""Nightmare Studio: a local editorial production desk for horror video episodes."""

from pathlib import Path
from dotenv import load_dotenv

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.is_file():
    load_dotenv(_env_file)
