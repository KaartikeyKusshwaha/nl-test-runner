from nlqa.config import Settings


def test_default_model_budgets_are_small_for_free_tier() -> None:
    settings = Settings(_env_file=None)

    assert settings.nlqa_max_elements == 60
    assert settings.nlqa_max_tokens == 512
