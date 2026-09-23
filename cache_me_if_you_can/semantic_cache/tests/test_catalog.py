from pathlib import Path

from semantic_cache.catalog import load_faq_directory


def test_data_directory_is_parsed_into_managed_service_faq_entries():
    data_dir = Path(__file__).resolve().parents[2] / "data"

    entries, corpus_version = load_faq_directory(data_dir)

    providers = {entry.provider for entry in entries}
    questions = {entry.question for entry in entries}
    assert len(entries) >= 50
    assert len(corpus_version) == 64
    assert {
        "Amazon ElastiCache",
        "Google Cloud Memorystore",
        "Heroku Key-Value Store",
        "Momento Cache",
        "OCI Cache",
    } <= providers
    assert "What deployment options do I have for ElastiCache?" in questions
    assert "What is OCI Cache?" in questions
