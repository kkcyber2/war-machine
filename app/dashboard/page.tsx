import { getAdminClient, type Lead, type PipelineStats, type WarMachineStats } from "@/lib/supabase";
import DashboardClient from "@/components/dashboard-client";

export const dynamic = "force-dynamic";
export const revalidate = 0;

async function fetchStats(): Promise<PipelineStats> {
  try {
    const sb = getAdminClient();
    const { data } = await sb
      .from("leads")
      .select("status");

    const counts: Record<string, number> = {};
    for (const row of data ?? []) {
      counts[row.status] = (counts[row.status] ?? 0) + 1;
    }

    return {
      new:          counts.new          ?? 0,
      emailed:      counts.emailed      ?? 0,
      clicked:      counts.clicked      ?? 0,
      responded:    counts.responded    ?? 0,
      converted:    counts.converted    ?? 0,
      bounced:      counts.bounced      ?? 0,
      unsubscribed: counts.unsubscribed ?? 0,
    };
  } catch {
    return { new: 0, emailed: 0, clicked: 0, responded: 0, converted: 0, bounced: 0, unsubscribed: 0 };
  }
}

async function fetchAggregateStats(): Promise<WarMachineStats | null> {
  try {
    const sb = getAdminClient();
    const { data } = await sb
      .from("war_machine_stats")
      .select("total_scraped, total_emailed, total_clicks, updated_at")
      .limit(1)
      .maybeSingle();
    return data as WarMachineStats | null;
  } catch {
    return null;
  }
}

async function fetchLeads(): Promise<Lead[]> {
  try {
    const sb = getAdminClient();
    const { data } = await sb
      .from("leads")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(200);
    return (data as Lead[]) ?? [];
  } catch {
    return [];
  }
}

export default async function DashboardPage() {
  const [stats, leads, aggregate] = await Promise.all([
    fetchStats(),
    fetchLeads(),
    fetchAggregateStats(),
  ]);

  const totalLeads       = aggregate?.total_scraped ?? Object.values(stats).reduce((a, b) => a + b, 0);
  const hooksGenerated   = leads.filter((l) => l.scare_hook).length;
  const emailsSent       = aggregate?.total_emailed ?? (stats.emailed + stats.clicked + stats.responded + stats.converted);
  const ctr              = emailsSent > 0
    ? Math.round(((aggregate?.total_clicks ?? stats.clicked + stats.responded + stats.converted) / emailsSent) * 100)
    : 0;

  return (
    <DashboardClient
      stats={stats}
      leads={leads}
      kpis={{ totalLeads, hooksGenerated, emailsSent, ctr }}
      aggregate={aggregate}
    />
  );
}
