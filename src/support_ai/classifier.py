"""Классификатор темы: TF-IDF + LogisticRegression. Владелец: Agent A, блок 1."""

import json
from threading import Lock

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from . import config
from .contracts import Classification


_model: tuple[TfidfVectorizer, LogisticRegression] | None = None
_model_lock = Lock()


def _get_model() -> tuple[TfidfVectorizer, LogisticRegression]:
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            rows = [json.loads(line) for line in config.TRAIN_TICKETS.read_text().splitlines() if line]
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
            features = vectorizer.fit_transform(row["text"] for row in rows)
            estimator = LogisticRegression(C=10.0, max_iter=1_000, random_state=0)
            estimator.fit(features, [row["label"] for row in rows])
            _model = vectorizer, estimator
    return _model


def predict(text: str) -> Classification:
    """Тема, калиброванная confidence и top-3. UNKNOWN при confidence < CONF_THRESHOLD."""
    vectorizer, estimator = _get_model()
    probabilities = estimator.predict_proba(vectorizer.transform([text]))[0]
    ranked = sorted(
        zip(estimator.classes_, probabilities, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    confidence = float(ranked[0][1])
    return Classification(
        topic=str(ranked[0][0]) if confidence >= config.CONF_THRESHOLD else "UNKNOWN",
        confidence=confidence,
        topk=[(str(label), float(score)) for label, score in ranked[:3]],
        model_version=config.VERSIONS["classifier"],
    )
