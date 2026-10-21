"""Upsert the researched price lists into MongoDB.

Usage (from backend/):  .venv/bin/python -m scripts.seed_prices [state ...]
"""

import sys

from app import create_app
from app.db import get_db
from app.services.catalog_prices import DATASETS, seed_prices


def main(states: list[str]) -> None:
    app = create_app()
    with app.app_context():
        for state in states or sorted(DATASETS):
            count = seed_prices(get_db(), state)
            print(f"{state}: upserted {count} prices")


if __name__ == "__main__":
    main(sys.argv[1:])
