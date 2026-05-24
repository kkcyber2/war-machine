/**
 * GET /api/track/[token]
 * Shadow Agency Click Tracker — War Machine outreach link handler.
 */

import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const REDIRECT_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://forgeguard.ai";

function getAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";
  if (!url || !key) throw new Error("Supabase env vars not set");
  return createClient(url, key, { auth: { persistSession: false } });
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;

  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!token || !UUID_RE.test(token)) {
    return NextResponse.redirect(REDIRECT_URL, { status: 301 });
  }

  try {
    const sb = getAdminClient();

    const { data } = await sb
      .from("leads")
      .update({ status: "clicked", clicked_at: new Date().toISOString() })
      .eq("click_token", token)
      .neq("status", "clicked")
      .select("company_name, website_url")
      .maybeSingle();

    if (data) {
      const { data: statsRow } = await sb
        .from("war_machine_stats")
        .select("id, total_clicks")
        .limit(1)
        .maybeSingle();

      if (statsRow?.id) {
        await sb
          .from("war_machine_stats")
          .update({
            total_clicks: (statsRow.total_clicks ?? 0) + 1,
            updated_at: new Date().toISOString(),
          })
          .eq("id", statsRow.id);
      }
    }
  } catch (err) {
    console.error("[track] DB update failed:", err);
  }

  return NextResponse.redirect(REDIRECT_URL, { status: 301 });
}
