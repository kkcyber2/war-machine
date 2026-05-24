-- War Machine — aggregate pipeline stats (single-row rollup)

CREATE TABLE IF NOT EXISTS public.war_machine_stats (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  total_scraped  INTEGER     NOT NULL DEFAULT 0,
  total_emailed  INTEGER     NOT NULL DEFAULT 0,
  total_clicks   INTEGER     NOT NULL DEFAULT 0,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure one stats row exists
INSERT INTO public.war_machine_stats (total_scraped, total_emailed, total_clicks)
SELECT 0, 0, 0
WHERE NOT EXISTS (SELECT 1 FROM public.war_machine_stats LIMIT 1);

ALTER TABLE public.war_machine_stats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role manages war_machine_stats"
  ON public.war_machine_stats
  FOR ALL
  USING (true)
  WITH CHECK (true);
