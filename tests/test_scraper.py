"""Tests for the lead-classification and contact-extraction helpers.

These cover the pure functions, which is where the logic that decides what gets
emailed actually lives. No browser, no network, no credentials needed.
"""
import pytest

from scraper import clean, guess_email, infer_rank


class TestClean:
    def test_collapses_internal_whitespace(self):
        assert clean("Acme   Robotics\n\tInc") == "Acme Robotics Inc"

    def test_trims_edges(self):
        assert clean("   padded   ") == "padded"

    def test_none_and_empty_become_empty_string(self):
        assert clean(None) == ""
        assert clean("") == ""
        assert clean("   ") == ""


class TestInferRank:
    def test_series_a_and_above_are_admirals(self):
        for phrase in ("Series A", "series b", "Series C", "IPO", "$20M", "$50M", "Raised $"):
            assert infer_rank(phrase) == "Admiral", phrase

    def test_seed_and_launch_are_lieutenants(self):
        for phrase in ("seed round", "pre-series", "$2M", "launched", "YC W24"):
            assert infer_rank(phrase) == "Lieutenant", phrase

    def test_unknown_is_recruit(self):
        assert infer_rank("") == "Recruit"
        assert infer_rank("a small studio") == "Recruit"

    def test_batch_argument_contributes(self):
        assert infer_rank("", "YC S23") == "Lieutenant"

    def test_series_a_outranks_seed_in_the_same_description(self):
        # A company that raised a Series A and mentions its seed history is
        # an Admiral today; the higher signal must win.
        assert infer_rank("Raised seed in 2021, then Series A in 2023") == "Admiral"

    def test_lowercase_series_a_is_still_detected(self):
        assert infer_rank("raised a series a round") == "Admiral"


class TestGuessEmail:
    def test_builds_founder_address_from_domain(self):
        assert guess_email("Acme", "https://acme.com") == "founder@acme.com"

    def test_strips_www_and_path(self):
        assert guess_email("Acme", "https://www.acme.io/about/team") == "founder@acme.io"

    def test_returns_empty_for_missing_url(self):
        assert guess_email("Acme", "") == ""
        assert guess_email("Acme", None) == ""

    def test_returns_empty_for_url_without_a_dot(self):
        assert guess_email("Acme", "https://localhost") == ""

    def test_preserves_subdomain_free_host(self):
        assert guess_email("Acme", "http://acme-robotics.dev") == "founder@acme-robotics.dev"
