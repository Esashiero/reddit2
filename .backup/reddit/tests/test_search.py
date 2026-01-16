import pytest
from app import RedditSearchEngine

def test_parse_keywords_simple():
    keywords = "(term1 OR term2) AND term3"
    expected = [["term1", "term2"], ["term3"]]
    assert RedditSearchEngine.parse_keywords(keywords) == expected

def test_parse_keywords_with_quotes_and_mixed_case():
    keywords = '("Term1" OR Term2) AND "Term3"'
    expected = [["term1", "term2"], ["term3"]]
    assert RedditSearchEngine.parse_keywords(keywords) == expected
