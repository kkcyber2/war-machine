-- War Machine — contact provenance
--
-- Why this migration exists
-- ─────────────────────────────────────────────────────────────────────────────
-- The original pipeline decided a lead's email address by inventing it:
-- `guess_email()` returned `founder@<their-domain>` for every company scraped,
-- and outreach.py mailed that address without ever checking it existed.
--
-- There was no column recording where an address came from, so nothing could
-- distinguish a mailbox a company published from one we made up. This adds that
-- column, and backfills every existing row as 'guessed' — because every address
-- currently in the table was produced by that function. That is the honest
-- backfill: it marks the whole existing set as unsendable, which is correct.
--
-- outreach_policy.evaluate_send() refuses any lead whose contact_source is not
-- one of the published values, so after this migration the historical rows stop
-- being mailable without anyone having to delete them.

ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS contact_source TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.leads.contact_source IS
  'Where the address came from. Only site_mailto, site_text, platform_contact '
  'and manual are sendable. ''guessed'' means the address was synthesised and '
  'must never be mailed. Empty means unknown provenance — also never mailed.';

-- Backfill: every pre-existing address came from guess_email().
UPDATE public.leads
   SET contact_source = 'guessed'
 WHERE email IS NOT NULL
   AND email <> ''
   AND contact_source = '';

-- Constrain the vocabulary so a typo cannot silently create a new, sendable
-- provenance value. '' is allowed for rows with no address at all.
ALTER TABLE public.leads
  DROP CONSTRAINT IF EXISTS leads_contact_source_check;

ALTER TABLE public.leads
  ADD CONSTRAINT leads_contact_source_check
  CHECK (contact_source IN ('', 'guessed', 'site_mailto', 'site_text',
                            'platform_contact', 'manual'));

-- The gate queries these two shapes on every run: who has been mailed recently
-- (cooldown) and who opted out (suppression). Both filter on emailed_at.
CREATE INDEX IF NOT EXISTS leads_emailed_at_idx
  ON public.leads (emailed_at DESC)
  WHERE emailed_at IS NOT NULL;

-- Suppression lookups filter on status; the existing leads_status_idx covers
-- the equality match, but a partial index keeps the opt-out query cheap as the
-- table grows.
CREATE INDEX IF NOT EXISTS leads_suppression_idx
  ON public.leads (status, email)
  WHERE status IN ('unsubscribed', 'bounced', 'responded');

-- Guard against the v1 failure mode at the database level: a row that has been
-- mailed must never be reset to 'new' without also clearing emailed_at, because
-- get_unsent_leads() would otherwise re-select it and mail it again.
CREATE OR REPLACE FUNCTION public.leads_guard_remail()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.status = 'new'
     AND OLD.emailed_at IS NOT NULL
     AND NEW.emailed_at IS NOT DISTINCT FROM OLD.emailed_at THEN
    RAISE EXCEPTION
      'lead % was already emailed at %; clear emailed_at explicitly to re-queue it',
      OLD.id, OLD.emailed_at;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS leads_guard_remail_trg ON public.leads;

CREATE TRIGGER leads_guard_remail_trg
  BEFORE UPDATE ON public.leads
  FOR EACH ROW
  EXECUTE FUNCTION public.leads_guard_remail();
