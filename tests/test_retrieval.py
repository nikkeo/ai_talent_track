from src.support_ai import config
from src.support_ai.retrieval import search


def test_video_problem_finds_technical_article_first() -> None:
    result = search("не воспроизводится видео", "TECHNICAL")

    assert result.hits[0].doc_id == "KB-TECH-125"
    assert result.max_score >= config.RELEVANCE_THRESHOLD
    assert result.query_topic == "TECHNICAL"
    assert result.threshold_used == config.RELEVANCE_THRESHOLD
    assert result.hits[0].topic_match is True


def test_missing_kb_subject_stays_below_relevance_threshold() -> None:
    result = search(
        "где оформить бумажный сертификат для участия в олимпиаде",
        "HOWTO",
    )

    assert result.max_score < config.RELEVANCE_THRESHOLD


def test_wrong_predicted_topic_does_not_filter_textually_relevant_article() -> None:
    result = search("не воспроизводится видео", "PAYMENT")

    assert result.hits[0].doc_id == "KB-TECH-125"
    assert result.hits[0].topic_match is False
    assert result.max_score >= config.RELEVANCE_THRESHOLD
