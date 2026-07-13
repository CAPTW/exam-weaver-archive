from scripts.analyze_maritime_law_pdfs import KNOWN_PAGE_RANGES


def test_2018_law_groups_exclude_adjacent_navigation_and_engineering_pages():
    ranges = KNOWN_PAGE_RANGES["[기출문제]해사법규(21년 경사-13년).pdf"]

    assert ranges[14] == (66, 69)
    assert ranges[15] == (70, 72)
    assert ranges[16] == (78, 80)
