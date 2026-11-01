"""Tests for the lead-classification and contact-extraction helpers.

These cover the pure functions, which is where the logic that decides what gets
emailed actually lives. No browser, no network, no credentials needed.

`TestGuessEmail` used to live here and asserted that `guess_email()` built
`founder@<domain>` from a website URL. Those tests passed, and that was the
problem: they locked in the fabrication. The function is gone, so the tests are
replaced by ones covering what took its place — extracting addresses a company
actually published, and refusing the ones that must never be mailed.
"""
import pytest

from scraper import _pick_published_address, clean, emails_in_text, infer_rank


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


class TestEmailsInText:
    """Addresses printed as visible text, not wrapped in a mailto: link."""

    def test_finds_a_plain_address(self):
        assert emails_in_text("Questions? Write to hello@acme.com.") == ["hello@acme.com"]

    def test_finds_several_and_dedupes(self):
        text = "hello@acme.com or sales@acme.com, again hello@acme.com"
        assert emails_in_text(text) == ["hello@acme.com", "sales@acme.com"]

    def test_normalises_case(self):
        assert emails_in_text("Contact Hello@Acme.COM") == ["hello@acme.com"]

    def test_ignores_text_without_an_address(self):
        assert emails_in_text("No contact details on this page.") == []

    def test_handles_none_and_empty(self):
        assert emails_in_text(None) == []
        assert emails_in_text("") == []

    def test_rejects_malformed_candidates(self):
        # A bare @ or a trailing dot is not a mailbox.
        assert emails_in_text("not-an-email@ or @acme.com") == []


class TestPickPublishedAddress:
    """Choosing among addresses the company published itself."""

    def test_prefers_a_personal_mailbox_over_a_generic_one(self):
        assert _pick_published_address(["info@acme.com", "jane@acme.com"]) == "jane@acme.com"

    def test_falls_back_to_generic_when_it_is_all_there_is(self):
        assert _pick_published_address(["hello@acme.com"]) == "hello@acme.com"

    def test_never_returns_an_automated_desk(self):
        # Mailing these guarantees a complaint without reaching a person.
        for desk in ("abuse@acme.com", "postmaster@acme.com", "no-reply@acme.com"):
            assert _pick_published_address([desk]) == "", desk

    def test_drops_the_desk_but_keeps_a_real_address(self):
        assert _pick_published_address(["abuse@acme.com", "jane@acme.com"]) == "jane@acme.com"

    def test_returns_empty_when_nothing_usable(self):
        assert _pick_published_address([]) == ""
        assert _pick_published_address(["not-an-address"]) == ""

    def test_ignores_invalid_entries(self):
        assert _pick_published_address(["broken@", "jane@acme.com"]) == "jane@acme.com"
