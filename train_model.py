"""train_model.py
Simple script to train the TF-IDF + classifiers on historical ticket data.

Usage:
    python train_model.py

This will write `app/data/ml_model.joblib` which the server will use for
prediction via `app.services.ml.predict_ticket`.
"""
from pathlib import Path
import logging
from app.services.ml import train_models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("train_model")


def main():
    db_path = Path(__file__).resolve().parent / "tickets.db"
    logger.info("Training ML models using database at %s", db_path)
    train_models(db_path=db_path)


if __name__ == "__main__":
    main()
