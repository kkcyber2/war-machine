"""
outreach_policy.py — the gate every outbound email must pass through
─────────────────────────────────────────────────────────────────────────────
Why this module exists
─────────────────────────────────────────────────────────────────────────────
The first version of this pipeline decided a lead's email address by
*inventing* it: `guess_email()` returned `founder@<their-domain>` for every
company it scraped, and outreach.py mailed that address without ever checking
it existed. That is the textbook definition of spam:

  • the address is unverified, so the majority of sends land in a mailbox that
    nobody at the company actually reads — a shared role inbox, an old alias,
    or an unrelated person who bought the domain;
  • every one of those inboxes yields a complaint or a hard bounce, and
    complaint rate is the single metric mailbox providers use to blacklist a
    sending domain;
  • the same lead was re-selected and re-mailed on every run, with no volume
    cap, no sending window, no per-domain cooldown and no working opt-out;
  • the copy asserted a specific security finding ("our recon systems flagged
    you", "VULNERABILITY DETECTED") that the pipeline never produced — it was
    LLM speculation over a marketing blurb, plus a P.S. hinting the findings
    would be published if they did not reply.

This module replaces all of that with one explicit, testable decision function.
It is deliberately PURE: no network, no database, no clock of its own. The
clock, the suppression list and the counters are passed in, so the rules can be
unit-tested exhaustively and no caller can quietly skip them.

The policy, in words:

  1. Never send to an address we synthesised. A recipient must be an address
     its owner published, and we must have a record of where we found it.
  2. Never send to an automated desk (postmaster, abuse, no-reply, …).
  3. Never send to an address or domain that opted out, bounced, or replied.
  4. Never mail the same domain twice inside the cooldown window.
  5. Never exceed the daily cap.
  6. Only send inside business hours on business days.
  7. Only send when a real postal address is configured (CAN-SPAM / GDPR
     require the sender to be identifiable), and every message carries a
     one-click unsubscribe.

Anything the gate cannot positively confirm is a refusal. Refusing a send costs
one lead; sending to a guessed address costs the domain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Provenance — where the address came from
# ─────────────────────────────────────────────────────────────────────────────
# The value stored in leads.contact_source. Only the entries in
# SENDABLE_CONTACT_SOURCES may be mailed: each of them means the recipient (or
# their employer) published that address themselves.
#
# "guessed" is intentionally absent. It is the historical behaviour — a
# synthesised `founder@domain` — and it is never sendable, not even behind a
# flag. There is no configuration under which inventing a mailbox is correct,
# so the gate does not offer one.

CONTACT_SOURCE_SITE_MAILTO = "site_mailto"        # mailto: link on their own site
CONTACT_SOURCE_SITE_TEXT = "site_text"            # address printed in page text
CONTACT_SOURCE_PLATFORM = "platform_contact"      # contact shown on YC / PH listing
CONTACT_SOURCE_MANUAL = "manual"                  # operator pasted a real address
CONTACT_SOURCE_GUESSED = "guessed"                # synthesised — NEVER sendable

SENDABLE_CONTACT_SOURCES = frozenset({
    CONTACT_SOURCE_SITE_MAILTO,
    CONTACT_SOURCE_SITE_TEXT,
    CONTACT_SOURCE_PLATFORM,
    CONTACT_SOURCE_MANUAL,
})

# Local parts that are automated desks, not people. Mailing these guarantees a
# complaint at best and a blocklisting at worst, whatever the provenance.
NEVER_SEND_LOCAL_PARTS = frozenset({
    "abuse", "postmaster", "hostmaster", "webmaster", "noreply", "no-reply",
    "donotreply", "do-not-reply", "mailer-daemon", "bounce", "bounces",
    "dmarc", "spam", "phishing", "security", "cert", "root", "null",
    "unsubscribe", "compliance", "legal",
})

# Addresses that look like placeholders someone typed into a template and
# forgot to replace. They are never deliverable.
PLACEHOLDER_LOCAL_PARTS = frozenset({
    "example", "test", "user", "email", "your-email", "youremail", "name",
    "yourname", "someone", "foo", "bar", "admin@example",
})

EMAIL_RE = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}"
)

# A short, deliberately incomplete list of two-label public suffixes. Without
# the `publicsuffix2` dependency we cannot resolve registrable domains exactly,
# so cooldown matching is a heuristic — documented here so nobody assumes it is
# authoritative. Over-grouping (treating mail.acme.com and acme.com as one
# domain) is the safe direction to be wrong in: it sends less, not more.
_TWO_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.nz", "net.nz", "org.nz",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
    "com.br", "net.br", "org.br",
    "co.in", "net.in", "org.in", "ac.in", "gov.in",
    "co.za", "org.za", "web.za",
    "com.sg", "com.hk", "com.mx", "com.tr", "com.cn", "com.tw",
    "co.kr", "or.kr", "co.il", "org.il", "com.pk", "com.ng", "com.eg",
})

# ─────────────────────────────────────────────────────────────────────────────
# Decision object
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SendDecision:
    """The verdict for one candidate send.

    `code` is stable and machine-readable so the caller can count refusals by
    reason in the run summary, which is how you notice the gate is doing
    something useful instead of guessing whether it ran.
    """

    allowed: bool
    code: str
    detail: str = ""

    def __bool__(self) -> bool:  # allows `if decision:`
        return self.allowed


ALLOW = "ok"

# Refusal codes, in the order the gate evaluates them.
R_NO_EMAIL = "no_email"
R_SYNTHESISED = "synthesised_address"
R_UNKNOWN_PROVENANCE = "unknown_provenance"
R_MALFORMED = "malformed_address"
R_AUTOMATED_DESK = "automated_desk"
R_PLACEHOLDER = "placeholder_address"
R_SUPPRESSED_EMAIL = "suppressed_email"
R_SUPPRESSED_DOMAIN = "suppressed_domain"
R_ALREADY_CONTACTED = "already_contacted"
R_COOLDOWN = "domain_cooldown"
R_ALREADY_SENT_STATUS = "lead_already_contacted"
R_DAILY_CAP = "daily_cap_reached"
R_SEND_WINDOW = "outside_send_window"
R_NO_POSTAL_ADDRESS = "no_postal_address"
R_NO_UNSUBSCRIBE = "no_unsubscribe"


# ─────────────────────────────────────────────────────────────────────────────
# Address helpers
# ─────────────────────────────────────────────────────────────────────────────


def normalise_email(email: Optional[str]) -> str:
    """Lowercase and trim. Returns "" for None/blank.

    Suppression lists and dedupe comparisons must use this, otherwise
    `Founder@Acme.com` and `founder@acme.com` count as two different leads and
    the same person gets mailed twice.
    """
    if not email:
        return ""
    return email.strip().strip(".,;:<>()[]\"'").lower()


def is_valid_email(email: Optional[str]) -> bool:
    candidate = normalise_email(email)
    if not candidate or len(candidate) > 254:
        return False
    if candidate.count("@") != 1:
        return False
    local, _, domain = candidate.partition("@")
    if not local or len(local) > 64:
        return False
    if not EMAIL_RE.fullmatch(candidate):
        return False
    # A bare TLD or a numeric TLD is not a real mailbox.
    if "." not in domain or domain.rsplit(".", 1)[-1].isdigit():
        return False
    return True


def local_part(email: str) -> str:
    return normalise_email(email).partition("@")[0]


def domain_of(email: str) -> str:
    """The full host of an address, lowercased. "" when not an address."""
    candidate = normalise_email(email)
    if not is_valid_email(candidate):
        return ""
    return candidate.partition("@")[2]


def registrable_domain(host: str) -> str:
    """Best-effort registrable domain for cooldown matching.

    `mail.acme.co.uk` → `acme.co.uk`. Heuristic, not Public-Suffix-List exact;
    see the note on _TWO_LABEL_SUFFIXES.
    """
    host = (host or "").strip().lower().strip(".")
    if not host:
        return ""
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return host
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def domain_key(email_or_host: str) -> str:
    """Cooldown key for an address or a bare host.

    Accepts a full URL as well as a host, because callers pass `website_url`
    straight from the database. Without stripping the scheme, `https://acme.com`
    parses as a host named `https://acme.com` and never matches `acme.com` —
    which silently disabled both the cooldown and the domain block list.
    """
    raw = (email_or_host or "").strip().lower()
    if "@" in raw:
        host = domain_of(raw)
    else:
        host = raw.split("//")[-1]          # drop scheme
        host = host.split("/")[0]           # drop path
        host = host.split("?")[0].split("#")[0]
        host = host.split(":")[0]           # drop port
    return registrable_domain(host)


def looks_synthesised(email: str, company_domain: Optional[str] = None) -> bool:
    """True when the address matches the shape of our own old guess.

    Belt-and-braces: provenance is the primary control, but if a legacy row in
    the database still holds `founder@<domain>` with a blank or missing
    contact_source, this keeps it out of the queue rather than trusting a
    column that was added after the row was written.
    """
    candidate = normalise_email(email)
    if not is_valid_email(candidate):
        return False
    local = local_part(candidate)
    if local in {"founder", "founders", "ceo", "cto", "hi", "cofounder"}:
        # Only suspicious when it is also the exact domain we scraped — a
        # genuinely published ceo@acme.com still has to clear provenance,
        # but this catches the historical fabrication.
        if company_domain:
            return domain_key(candidate) == domain_key(company_domain)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────────


def within_send_window(
    now: Optional[datetime] = None,
    start_hour: int = 8,
    end_hour: int = 18,
    allow_weekends: bool = False,
) -> bool:
    """Business hours in UTC. Cold mail that arrives at 03:00 reads as a bot.

    Requires a timezone-aware `now`; a naive datetime is rejected rather than
    silently assumed to be local time, because this box runs UTC but CI does
    not always.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("within_send_window requires a timezone-aware datetime")
    if not allow_weekends and now.weekday() >= 5:
        return False
    if start_hour <= end_hour:
        return start_hour <= now.hour < end_hour
    # Window wraps past midnight, e.g. 22 → 06.
    return now.hour >= start_hour or now.hour < end_hour


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_send(
    lead: Mapping[str, object],
    *,
    now: Optional[datetime] = None,
    suppressed_emails: Iterable[str] = (),
    suppressed_domains: Iterable[str] = (),
    contacted_domains: Iterable[str] = (),
    sent_today: int = 0,
    daily_cap: int = 40,
    cooldown_days: int = 180,
    start_hour: int = 8,
    end_hour: int = 18,
    allow_weekends: bool = False,
    postal_address: str = "",
    unsubscribe_url: str = "",
    enforce_window: bool = True,
) -> SendDecision:
    """Decide whether this lead may be emailed right now.

    Every input the rules depend on is a parameter, so the caller owns the
    clock, the database and the counters and this function stays pure. A
    refusal is the default: each `return` below is a positive finding that the
    send is safe.
    """
    email = normalise_email(str(lead.get("email") or ""))
    source = str(lead.get("contact_source") or "").strip().lower()
    website = str(lead.get("website_url") or "")

    # 1. There has to be an address at all.
    if not email:
        return SendDecision(False, R_NO_EMAIL, "lead has no email address")

    # 2. Provenance. This is the control that stops the historical spam: a
    #    lead whose address we invented has contact_source='guessed', and one
    #    written before the column existed has '' — both refuse.
    if source == CONTACT_SOURCE_GUESSED:
        return SendDecision(
            False, R_SYNTHESISED,
            "address was synthesised (founder@domain), never a published mailbox",
        )
    if source not in SENDABLE_CONTACT_SOURCES:
        return SendDecision(
            False, R_UNKNOWN_PROVENANCE,
            f"contact_source={source or '<empty>'} is not a published address",
        )

    # 3. Shape. Cheap, and it catches scraped junk before any other work.
    if not is_valid_email(email):
        return SendDecision(False, R_MALFORMED, f"{email!r} is not a valid address")

    local = local_part(email)
    if local in NEVER_SEND_LOCAL_PARTS:
        return SendDecision(
            False, R_AUTOMATED_DESK,
            f"{email} is an automated desk, not a person who can consent",
        )
    if local in PLACEHOLDER_LOCAL_PARTS:
        return SendDecision(False, R_PLACEHOLDER, f"{email} looks like a template placeholder")

    # Legacy safety net: a row carrying a fabricated address but a provenance
    # label that got backfilled by hand still gets caught here.
    if looks_synthesised(email, website):
        return SendDecision(
            False, R_SYNTHESISED,
            f"{email} matches the shape of a fabricated founder@ address",
        )

    # 4. Opt-outs, bounces and replies are absolute.
    if email in {normalise_email(e) for e in suppressed_emails}:
        return SendDecision(False, R_SUPPRESSED_EMAIL, f"{email} is on the suppression list")

    domain = domain_key(email)
    blocked_domains = {domain_key(d) for d in suppressed_domains if d}
    if domain and domain in blocked_domains:
        return SendDecision(
            False, R_SUPPRESSED_DOMAIN,
            f"{domain} opted out, bounced, or asked us to stop",
        )

    # 5. Never resurrect a lead we already mailed. The old get_unsent_leads()
    #    relied on status alone, so any row reset to 'new' by an operator or a
    #    migration went straight back into the queue.
    status = str(lead.get("status") or "").strip().lower()
    if status in {"emailed", "clicked", "responded", "converted", "bounced", "unsubscribed"}:
        return SendDecision(
            False, R_ALREADY_SENT_STATUS,
            f"lead status is {status!r} — already contacted",
        )
    if lead.get("emailed_at"):
        return SendDecision(False, R_ALREADY_CONTACTED, "emailed_at is already set")

    # 6. Per-domain cooldown, independent of which mailbox we are using. Two
    #    different people at the same company in the same week is the pattern
    #    that gets a domain reported.
    if domain:
        cooldown_cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=cooldown_days)
        for entry in contacted_domains:
            if not entry:
                continue
            if "|" in str(entry):
                recorded_domain, _, recorded_at = str(entry).partition("|")
                if domain_key(recorded_domain) != domain:
                    continue
                try:
                    stamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
                except ValueError:
                    return SendDecision(
                        False, R_COOLDOWN,
                        f"{domain} was contacted at an unparseable time {recorded_at!r}",
                    )
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp >= cooldown_cutoff:
                    return SendDecision(
                        False, R_COOLDOWN,
                        f"{domain} was already contacted on {stamp.date().isoformat()}",
                    )
            elif domain_key(str(entry)) == domain:
                return SendDecision(False, R_COOLDOWN, f"{domain} was already contacted")

    # 7. Volume. A cap is what turns an accidental loop into a bad hour
    #    instead of a burned domain.
    if sent_today >= daily_cap:
        return SendDecision(
            False, R_DAILY_CAP,
            f"{sent_today} already sent today (cap {daily_cap})",
        )

    # 8. Timing.
    if enforce_window and not within_send_window(
        now=now, start_hour=start_hour, end_hour=end_hour, allow_weekends=allow_weekends
    ):
        return SendDecision(False, R_SEND_WINDOW, "outside configured sending window")

    # 9. Identification and opt-out. Both are legal requirements wherever this
    #    is sent, so a missing one blocks the send rather than shipping an
    #    unlawful message.
    if not (postal_address or "").strip():
        return SendDecision(
            False, R_NO_POSTAL_ADDRESS,
            "POSTAL_ADDRESS is not configured — commercial email requires a "
            "real physical address in the footer",
        )
    if not (unsubscribe_url or "").strip():
        return SendDecision(False, R_NO_UNSUBSCRIBE, "no unsubscribe URL configured")

    return SendDecision(True, ALLOW, f"{email} cleared all send checks")


def explain(decision: SendDecision) -> str:
    """One-line human summary, used in logs and the run report."""
    if decision.allowed:
        return "SEND  " + decision.detail
    return f"HOLD  [{decision.code}] {decision.detail}"


# ─────────────────────────────────────────────────────────────────────────────
# Copy honesty guard
# ─────────────────────────────────────────────────────────────────────────────
# The old copy asserted that the pipeline had *found* something ("our automated
# recon systems flagged you", "VULNERABILITY DETECTED: <tag>"). Nothing was ever
# tested — the "vulnerability" was an LLM's guess from a one-paragraph marketing
# blurb. Asserting a finding you did not produce is deceptive, and where it names
# a real company it is defamation-shaped. This guard keeps the assertion out of
# the message, so a future template edit cannot quietly reintroduce it.

FORBIDDEN_CLAIM_PATTERNS = (
    r"we (?:found|detected|discovered|confirmed|identified)\b",
    r"vulnerabilit\w* (?:detected|confirmed|verified|found)",
    r"our (?:automated )?(?:recon|scan\w*|systems?)(?:\s+systems?)? (?:flagged|detected|found)",
    r"(?:you|your (?:site|app|platform|product)) (?:is|are) (?:vulnerable|exposed|compromised)",
    r"before we publish",
    r"we will publish",
    r"publish(?:ing)? the findings",
    r"already have (?:the )?(?:exploit|poc|proof)",
)

_FORBIDDEN_RE = re.compile("|".join(FORBIDDEN_CLAIM_PATTERNS), re.IGNORECASE)

# A claim is only a claim when it is asserted. The honest disclaimer this
# pipeline relies on — "I'm not claiming we found anything" — contains the
# literal phrase "we found", so a naive match would flag the very sentence that
# makes the email truthful and block every send. Negated matches are therefore
# skipped: the guard looks back a short window for a negation cue.
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|none|nothing|cannot|can't|won't|wouldn't|don't|doesn't|"
    r"didn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|without|"
    r"unable|nor|neither)\b|n't\b",
    re.IGNORECASE,
)

# How far back to look for a negation cue. Bounded by the start of the current
# sentence as well as by length: a negation in a *previous* sentence must not
# launder a real assertion in this one ("We are not an agency. We found a bug."
# is still a claim). Within a sentence, 60 characters covers
# "I'm not claiming that we found" comfortably.
_NEGATION_WINDOW = 60
_SENTENCE_BREAK_RE = re.compile(r"[.!?;:\n]")


def _clause_before(text: str, index: int) -> str:
    """The text between the previous sentence break and `index`, capped."""
    window_start = max(0, index - _NEGATION_WINDOW)
    prefix = text[window_start:index]
    breaks = list(_SENTENCE_BREAK_RE.finditer(prefix))
    if breaks:
        prefix = prefix[breaks[-1].end():]
    return prefix


def assert_honest_copy(text: str) -> list[str]:
    """Return the forbidden claim patterns *asserted* in `text` (empty = clean).

    Called by the outreach runner before every send, so a copy change that
    reintroduces a fabricated finding fails the run instead of reaching an
    inbox. Returning the hits (rather than raising) lets the caller log exactly
    which template line is at fault.

    Negated occurrences are ignored — see _NEGATION_RE. Without that, the
    disclaimer "we have not tested your systems, and I'm not claiming we found
    anything" would itself be reported as a violation.
    """
    if not text:
        return []
    seen: list[str] = []
    for match in _FORBIDDEN_RE.finditer(text):
        if _NEGATION_RE.search(_clause_before(text, match.start())):
            continue  # negated in this clause — a disclaimer, not an assertion
        phrase = match.group(0).strip()
        if phrase.lower() not in {s.lower() for s in seen}:
            seen.append(phrase)
    return seen


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    demo = {
        "company_name": "Acme",
        "website_url": "https://acme.com",
        "email": "founder@acme.com",
        "contact_source": "guessed",
        "status": "new",
    }
    print(explain(evaluate_send(demo, postal_address="x", unsubscribe_url="y")))
    honest = {
        "company_name": "Acme",
        "website_url": "https://acme.com",
        "email": "hello@acme.com",
        "contact_source": "site_mailto",
        "status": "new",
    }
    print(explain(evaluate_send(
        honest,
        now=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
        postal_address="1 Example St",
        unsubscribe_url="https://example.com/u/abc",
    )))
