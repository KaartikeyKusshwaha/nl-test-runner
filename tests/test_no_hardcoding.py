from pathlib import Path


def test_core_engine_has_no_site_names_urls_or_oracle_selectors() -> None:
    source_root = Path(__file__).resolve().parents[1] / "nlqa"
    forbidden = (
        "phptravels",
        "saucedemo",
        "herokuapp",
        "cloudqa",
        "automationpracticeform",
        "data-test",
    )
    for source in [*source_root.rglob("*.py"), *source_root.rglob("*.js")]:
        content = source.read_text(encoding="utf-8").casefold()
        for value in forbidden:
            assert value not in content, f"site-specific string {value!r} found in {source}"
