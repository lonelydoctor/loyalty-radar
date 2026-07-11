"""Collector API; the compatibility engine remains the v0.1 implementation."""

from .engine import (
    FetchError,
    SourceHealth,
    collect_all,
    collect_comment_items,
    collect_source,
    fetch_flyert_detail,
    filter_rows_by_source_keywords,
    http_get,
    parse_flyert_forum,
    parse_generic_html_keyword,
    parse_rss_feed,
)

__all__ = [
    "FetchError",
    "SourceHealth",
    "collect_all",
    "collect_comment_items",
    "collect_source",
    "fetch_flyert_detail",
    "filter_rows_by_source_keywords",
    "http_get",
    "parse_flyert_forum",
    "parse_generic_html_keyword",
    "parse_rss_feed",
]
