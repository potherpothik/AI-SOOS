from pathlib import Path


def test_page_has_a_title_and_main() -> None:
    page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert "<title>AI-SOOS site</title>" in page
    assert "<main>" in page
