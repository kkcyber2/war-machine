import { createClient } from "@supabase/supabase-js";

// Admin client — service role bypasses RLS (server-side only)
export function getAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";
  if (!url || !key) throw new Error("Supabase env vars missing");
  return createClient(url, key, { auth: { persistSession: false } });
}

// Public client — for dashboard reads (anon key)
export function getPublicClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  if (!url || !key) throw new Error("Supabase public env vars missing");
  return createClient(url, key);
}

export type LeadStatus =
  | "new"
  | "emailed"
  | "clicked"
  | "responded"
  | "converted"
  | "bounced"
  | "unsubscribed";

export type LeadRank = "Recruit" | "Lieutenant" | "Admiral";

export interface Lead {
  id:            string;
  company_name:  string;
  website_url:   string | null;
  founder_name:  string | null;
  email:         string | null;
  description:   string | null;
  source:        "yc" | "producthunt" | "x" | "manual";
  batch:         string | null;
  rank:          LeadRank;
  scare_hook:    string | null;
  vulnerability: string | null;
  subject_line:  string | null;
  status:        LeadStatus;
  click_token:   string;
  created_at:    string;
  emailed_at:    string | null;
  clicked_at:    string | null;
  responded_at:  string | null;
  resend_msg_id: string | null;
}

export interface PipelineStats {
  new:          number;
  emailed:      number;
  clicked:      number;
  responded:    number;
  converted:    number;
  bounced:      number;
  unsubscribed: number;
}

export interface WarMachineStats {
  total_scraped: number;
  total_emailed: number;
  total_clicks:  number;
  updated_at?:   string | null;
}
