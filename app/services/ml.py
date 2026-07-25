"""
ml.py
-----
Simple ML utilities for training and predicting ticket category and priority.

This module provides `predict_ticket(title, description)` which loads a
saved vectorizer and classifiers (joblib) and returns (category, priority).

It also exposes `train_models()` which is used by an external script to
train and persist models to `app/data/ml_model.joblib`.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Tuple

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline

from app.database import DB_PATH

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_PATH = DATA_DIR / "ml_model.joblib"

logger = logging.getLogger("ticket_system.ml")


def _ensure_data_dir():
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)


def train_models(db_path: Path | str = None) -> None:
    """Train TF-IDF + classifiers on historical tickets and persist model.

    Trains two classifiers using a shared TF-IDF vectorizer: one for
    category (LogisticRegression) and one for priority (MultinomialNB).
    """
    _ensure_data_dir()
    db_path = db_path or DB_PATH

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT title, description, category, priority FROM tickets WHERE title IS NOT NULL AND description IS NOT NULL")
    rows = cur.fetchall()
    con.close()

    texts = []
    cat_y = []
    pri_y = []
    for r in rows:
        title = r["title"] or ""
        desc = r["description"] or ""
        texts.append(f"{title} {desc}")
        cat_y.append(r["category"] or "Other")
        pri_y.append((r["priority"] or "LOW").upper())

    if not texts:
        raise RuntimeError("No training data available in database (tickets table).")

    # Shared vectorizer
    vectorizer = TfidfVectorizer(max_features=10000, ngram_range=(1, 2))
    X = vectorizer.fit_transform(texts)

    # Category classifier (multiclass)
    cat_clf = LogisticRegression(max_iter=1000)
    cat_clf.fit(X, cat_y)

    # Priority classifier (LOW/MEDIUM/HIGH) - MultinomialNB works well on tf-idf
    pri_clf = MultinomialNB()
    pri_clf.fit(X, pri_y)

    joblib.dump({"vectorizer": vectorizer, "category_clf": cat_clf, "priority_clf": pri_clf}, MODEL_PATH)
    logger.info("Saved ML model to %s", MODEL_PATH)


def _load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"ML model not found at {MODEL_PATH}")
    return joblib.load(MODEL_PATH)


def predict_ticket(title: str, description: str) -> Tuple[str, str]:
    """Return (predicted_category, predicted_priority) for the provided text.

    Raises FileNotFoundError if model not present.
    """
    model = _load_model()
    vectorizer = model["vectorizer"]
    cat_clf = model["category_clf"]
    pri_clf = model["priority_clf"]

    text = f"{title or ''} {description or ''}"
    X = vectorizer.transform([text])
    cat = cat_clf.predict(X)[0]
    pri = pri_clf.predict(X)[0]
    # Normalize outputs to expected formats
    return str(cat), str(pri)
