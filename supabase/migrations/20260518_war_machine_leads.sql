-- War Machine — leads table
-- Tracks scraped leads through: new → emailed → clicked → responded → converted

CREATE TABLE IF NOT EXISTS public.leads (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name   TEXT        NOT NULL,
  website_url    TEXT        UNIQUE,
  founder_name   TEXT,
  email          TEXT,
  description    TEXT,
  source         TEXT        NOT NULL DEFAULT 'manual'
                               CHECK (source IN ('yc', 'producthunt', 'x', 'manual')),
  batch          TEXT,
  rank           TEXT        NOT NULL DEFAULT 'Recruit'
                               CHECK (rank IN ('Recruit', 'Lieutenant', 'Admiral')),
  scare_hook     TEXT,
  vulnerability  TEXT,
  subject_line   TEXT,
  status         TEXT        NOT NULL DEFAULT 'new'
                               CHECK (status IN ('new','emailed','clicked','responded','converted','bounced','unsubscribed')),
  click_token    UUID        NOT NULL DEFAULT gen_random_uuid(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  emailed_at     TIMESTAMPTZ,
  clicked_at     TIMESTAMPTZ,
  responded_at   TIMESTAMPTZ,
  resend_msg_id  TEXT
);

CREATE INDEX IF NOT EXISTS leads_status_idx        ON public.leads (status);
CREATE INDEX IF NOT EXISTS leads_click_token_idx   ON public.leads (click_token);
CREATE INDEX IF NOT EXISTS leads_source_idx        ON public.leads (source);
CREATE INDEX IF NOT EXISTS leads_created_at_idx    ON public.leads (created_at DESC);

ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admin can read leads"
  ON public.leads FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.profiles
      WHERE profiles.user_id = auth.uid()
        AND profiles.access_level >= 4
    )
  );
