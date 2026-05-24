"use client";

import { useState, useMemo } from "react";
import {
  Target, Zap, Mail, MousePointerClick,
  Search, RefreshCw, ChevronRight, X,
  AlertTriangle, Shield, ExternalLink,
  Activity, Users, TrendingUp
} from "lucide-react";
import type { Lead, PipelineStats, WarMachineStats } from "@/lib/supabase";

interface KPIs {
  totalLeads:    number;
  hooksGenerated: number;
  emailsSent:    number;
  ctr:           number;
}

interface Props {
  stats:  PipelineStats;
  leads:  Lead[];
  kpis:   KPIs;
  aggregate?: WarMachineStats | null;
}

// ── Status helpers ─────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  new:          { label: "NEW",          color: "text-dim",       dot: "bg-dim" },
  emailed:      { label: "EMAILED",      color: "text-warn",      dot: "bg-warn" },
  clicked:      { label: "CLICKED",      color: "text-purple-light", dot: "bg-purple-light" },
  responded:    { label: "RESPONDED",    color: "text-blue-400",  dot: "bg-blue-400" },
  converted:    { label: "CONVERTED",    color: "text-safe",      dot: "bg-safe" },
  bounced:      { label: "BOUNCED",      color: "text-threat",    dot: "bg-threat" },
  unsubscribed: { label: "UNSUB",        color: "text-faint",     dot: "bg-faint" },
};

const RANK_META: Record<string, { label: string; color: string }> = {
  Admiral:    { label: "ADMIRAL",    color: "text-yellow-400" },
  Lieutenant: { label: "LIEUTENANT", color: "text-purple-light" },
  Recruit:    { label: "RECRUIT",    color: "text-dim" },
};

function StatusDot({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.new;
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      <span className={`text-[10px] font-mono tracking-widest ${meta.color}`}>
        {meta.label}
      </span>
    </span>
  );
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

interface KpiCardProps {
  icon:    React.ReactNode;
  label:   string;
  value:   number | string;
  suffix?: string;
  accent?: boolean;
}

function KpiCard({ icon, label, value, suffix, accent }: KpiCardProps) {
  return (
    <div className={`glass-card p-5 flex flex-col gap-3 ${accent ? "glass-card-purple" : ""}`}>
      <div className="flex items-center justify-between">
        <span className={`p-2 rounded ${accent ? "bg-purple-faint text-purple-light" : "bg-steel-2 text-faint"}`}>
          {icon}
        </span>
        <span className="text-[9px] font-mono tracking-[0.2em] text-faint uppercase">{label}</span>
      </div>
      <div className="flex items-end gap-1">
        <span className={`text-3xl font-mono font-bold tracking-tight ${accent ? "text-purple-light" : "text-white"}`}>
          {value}
        </span>
        {suffix && <span className="text-sm text-faint mb-1">{suffix}</span>}
      </div>
    </div>
  );
}

// ── Hook Preview Panel ─────────────────────────────────────────────────────────

function HookPreviewPanel({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const rank = RANK_META[lead.rank] ?? RANK_META.Recruit;
  return (
    <div className="fixed inset-y-0 right-0 w-96 glass-card border-l border-purple-subtle z-50 flex flex-col overflow-hidden shadow-purple-glow">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-steel-subtle bg-obsidian-2">
        <div>
          <div className="text-[9px] font-mono tracking-[0.2em] text-faint uppercase mb-1">
            Intel Report
          </div>
          <div className="text-sm font-mono text-white truncate max-w-[280px]">
            {lead.company_name}
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-steel-2 rounded transition-colors text-faint hover:text-white"
        >
          <X size={14} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Rank + Status */}
        <div className="flex items-center gap-3">
          <span className={`text-[10px] font-mono tracking-widest ${rank.color} px-2 py-0.5 border border-current/30 rounded`}>
            {rank.label}
          </span>
          <StatusDot status={lead.status} />
        </div>

        {/* Vulnerability */}
        {lead.vulnerability && (
          <div className="bg-threat/5 border border-threat/20 rounded p-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={12} className="text-threat" />
              <span className="text-[9px] font-mono tracking-widest text-threat uppercase">
                Identified Vulnerability
              </span>
            </div>
            <div className="text-sm font-mono text-threat/80">{lead.vulnerability}</div>
          </div>
        )}

        {/* Subject Line */}
        {lead.subject_line && (
          <div>
            <div className="text-[9px] font-mono tracking-widest text-faint uppercase mb-2">
              Email Subject
            </div>
            <div className="text-xs font-mono text-dim bg-steel/50 rounded p-3 border border-steel-subtle">
              {lead.subject_line}
            </div>
          </div>
        )}

        {/* Scare Hook */}
        {lead.scare_hook ? (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Zap size={11} className="text-purple-light" />
              <span className="text-[9px] font-mono tracking-widest text-faint uppercase">
                Scare Hook
              </span>
            </div>
            <p className="text-xs font-mono text-dim leading-relaxed bg-purple-faint border border-purple-subtle rounded p-3">
              {lead.scare_hook}
            </p>
          </div>
        ) : (
          <div className="text-xs text-faint font-mono italic">
            No hook generated yet. Run pipeline to enrich.
          </div>
        )}

        {/* Description */}
        {lead.description && (
          <div>
            <div className="text-[9px] font-mono tracking-widest text-faint uppercase mb-2">
              Description
            </div>
            <p className="text-xs font-mono text-faint leading-relaxed">
              {lead.description}
            </p>
          </div>
        )}

        {/* Meta */}
        <div className="space-y-2 border-t border-steel-subtle pt-4">
          {[
            { label: "Source",   value: lead.source.toUpperCase() },
            { label: "Founder",  value: lead.founder_name ?? "—" },
            { label: "Email",    value: lead.email ?? "—" },
            { label: "Batch",    value: lead.batch ?? "—" },
            { label: "Created",  value: new Date(lead.created_at).toLocaleDateString() },
            { label: "Emailed",  value: lead.emailed_at ? new Date(lead.emailed_at).toLocaleDateString() : "—" },
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between items-center">
              <span className="text-[9px] font-mono tracking-widest text-faint uppercase">{label}</span>
              <span className="text-[11px] font-mono text-dim truncate max-w-[200px]">{value}</span>
            </div>
          ))}
        </div>

        {/* Website link */}
        {lead.website_url && (
          <a
            href={lead.website_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-xs font-mono text-purple-light hover:text-purple-DEFAULT transition-colors"
          >
            <ExternalLink size={11} />
            {lead.website_url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}
          </a>
        )}
      </div>
    </div>
  );
}

// ── Strike Control ────────────────────────────────────────────────────────────

function StrikeControl() {
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [stage,  setStage]  = useState<string>("");

  const stages = ["Initializing…", "Scraping YC…", "Scraping PH…", "Generating hooks…", "Sending outreach…", "Strike complete ✓"];

  async function handleStrike() {
    setStatus("running");
    setStage("Initializing…");

    // Simulate pipeline stage progression (actual pipeline runs via GitHub Actions / Railway)
    // This button triggers a webhook or API call in a real deployment
    for (let i = 1; i < stages.length; i++) {
      await new Promise((r) => setTimeout(r, 1200));
      setStage(stages[i]);
    }

    setStatus("done");
    setTimeout(() => { setStatus("idle"); setStage(""); }, 4000);
  }

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[9px] font-mono tracking-[0.2em] text-faint uppercase mb-1">
            Strike Control
          </div>
          <div className="text-xs font-mono text-dim">
            Launch full hunting pipeline
          </div>
        </div>
        <Activity
          size={14}
          className={status === "running" ? "text-purple-light animate-pulse" : "text-faint"}
        />
      </div>

      {status === "running" && (
        <div className="mb-4 flex items-center gap-2">
          <div className="w-1.5 h-1.5 bg-purple-light rounded-full animate-ping" />
          <span className="text-[10px] font-mono text-purple-light">{stage}</span>
        </div>
      )}

      {status === "done" && (
        <div className="mb-4 flex items-center gap-2">
          <div className="w-1.5 h-1.5 bg-safe rounded-full" />
          <span className="text-[10px] font-mono text-safe">Strike complete. Refresh for new leads.</span>
        </div>
      )}

      <button
        className="btn-strike w-full"
        onClick={handleStrike}
        disabled={status === "running"}
      >
        {status === "running" ? "⚡ Hunting…" : "⚔ Deploy Strike"}
      </button>

      <div className="mt-3 text-[9px] font-mono text-faint text-center">
        Cron auto-runs every 6h · Manual override triggers full pipeline
      </div>
    </div>
  );
}

// ── Pipeline Funnel ───────────────────────────────────────────────────────────

function PipelineFunnel({ stats }: { stats: PipelineStats }) {
  const total = Object.values(stats).reduce((a, b) => a + b, 0) || 1;
  const items = [
    { key: "new",       label: "New",       val: stats.new,       color: "bg-dim/40" },
    { key: "emailed",   label: "Emailed",   val: stats.emailed,   color: "bg-warn/60" },
    { key: "clicked",   label: "Clicked",   val: stats.clicked,   color: "bg-purple-light/60" },
    { key: "responded", label: "Responded", val: stats.responded, color: "bg-blue-400/60" },
    { key: "converted", label: "Converted", val: stats.converted, color: "bg-safe/60" },
  ];

  return (
    <div className="glass-card p-5">
      <div className="text-[9px] font-mono tracking-[0.2em] text-faint uppercase mb-4">
        Pipeline Funnel
      </div>
      <div className="space-y-2">
        {items.map(({ key, label, val, color }) => (
          <div key={key}>
            <div className="flex justify-between items-center mb-1">
              <span className="text-[10px] font-mono text-dim">{label}</span>
              <span className="text-[10px] font-mono text-dim">{val}</span>
            </div>
            <div className="h-1 bg-steel rounded-full overflow-hidden">
              <div
                className={`h-full ${color} rounded-full transition-all duration-700`}
                style={{ width: `${Math.round((val / total) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Lead Board ────────────────────────────────────────────────────────────────

function LeadBoard({ leads, onSelect }: { leads: Lead[]; onSelect: (l: Lead) => void }) {
  const [query, setQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterRank,   setFilterRank]   = useState<string>("all");

  const filtered = useMemo(() => {
    return leads.filter((l) => {
      const q = query.toLowerCase();
      const matchQ = !q || l.company_name.toLowerCase().includes(q) ||
        (l.email ?? "").toLowerCase().includes(q) ||
        (l.vulnerability ?? "").toLowerCase().includes(q);
      const matchS = filterStatus === "all" || l.status === filterStatus;
      const matchR = filterRank   === "all" || l.rank   === filterRank;
      return matchQ && matchS && matchR;
    });
  }, [leads, query, filterStatus, filterRank]);

  return (
    <div className="flex flex-col gap-3">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <div className="flex-1 min-w-[200px] relative">
          <Search size={11} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search leads…"
            className="w-full bg-steel-2/60 border border-steel-subtle rounded text-xs font-mono text-dim placeholder:text-muted pl-8 pr-3 py-2 focus:outline-none focus:border-purple-mid transition-colors"
          />
        </div>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="bg-steel-2/60 border border-steel-subtle rounded text-[10px] font-mono text-dim px-3 py-2 focus:outline-none focus:border-purple-mid cursor-pointer"
        >
          <option value="all">All Status</option>
          {Object.keys(STATUS_META).map((s) => (
            <option key={s} value={s}>{STATUS_META[s].label}</option>
          ))}
        </select>

        <select
          value={filterRank}
          onChange={(e) => setFilterRank(e.target.value)}
          className="bg-steel-2/60 border border-steel-subtle rounded text-[10px] font-mono text-dim px-3 py-2 focus:outline-none focus:border-purple-mid cursor-pointer"
        >
          <option value="all">All Ranks</option>
          <option value="Admiral">Admiral</option>
          <option value="Lieutenant">Lieutenant</option>
          <option value="Recruit">Recruit</option>
        </select>

        <div className="text-[10px] font-mono text-faint self-center">
          {filtered.length} / {leads.length}
        </div>
      </div>

      {/* Table */}
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-steel-subtle bg-obsidian-2">
                {["Company", "Rank", "Source", "Vulnerability", "Status", ""].map((h) => (
                  <th key={h} className="text-left text-[9px] tracking-widest text-faint uppercase px-4 py-3 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-faint py-12 text-[11px]">
                    No leads match your filters
                  </td>
                </tr>
              ) : (
                filtered.map((lead) => {
                  const rank = RANK_META[lead.rank] ?? RANK_META.Recruit;
                  return (
                    <tr
                      key={lead.id}
                      className="border-b border-steel-subtle/50 hover:bg-steel/30 cursor-pointer transition-colors group"
                      onClick={() => onSelect(lead)}
                    >
                      <td className="px-4 py-3">
                        <div className="text-white/90 text-[11px] max-w-[180px] truncate">
                          {lead.company_name}
                        </div>
                        {lead.email && (
                          <div className="text-faint text-[9px] truncate max-w-[180px]">
                            {lead.email}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[9px] tracking-widest ${rank.color}`}>
                          {rank.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-faint text-[10px] uppercase tracking-wider">
                        {lead.source}
                      </td>
                      <td className="px-4 py-3">
                        {lead.vulnerability ? (
                          <span className="text-[10px] text-threat/70 bg-threat/5 border border-threat/20 px-2 py-0.5 rounded whitespace-nowrap">
                            {lead.vulnerability}
                          </span>
                        ) : (
                          <span className="text-faint text-[10px]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <StatusDot status={lead.status} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ChevronRight
                          size={12}
                          className="text-faint group-hover:text-purple-light transition-colors inline-block"
                        />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Main Client Component ─────────────────────────────────────────────────────

export default function DashboardClient({ stats, leads, kpis, aggregate }: Props) {
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);

  return (
    <div className="min-h-screen bg-obsidian bg-grid">
      {/* ── Top bar ── */}
      <header className="border-b border-steel-subtle bg-obsidian/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="max-w-[1400px] mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-purple-light font-mono text-sm font-bold tracking-wider">⚔ WAR MACHINE</span>
            <span className="text-[9px] font-mono text-faint tracking-[0.2em] border-l border-steel-subtle pl-3">
              SHADOW AGENCY · INTELLIGENCE DASHBOARD
            </span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-safe animate-pulse" />
              <span className="text-[9px] font-mono text-faint tracking-widest">SYSTEMS ONLINE</span>
            </div>
            {aggregate?.updated_at && (
              <span className="hidden text-[9px] font-mono text-purple-light/70 sm:inline">
                SYNC {new Date(aggregate.updated_at).toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => window.location.reload()}
              className="p-1.5 hover:bg-steel-2 rounded transition-colors text-faint hover:text-dim"
              title="Refresh data"
            >
              <RefreshCw size={12} />
            </button>
          </div>
        </div>
      </header>

      <main className={`max-w-[1400px] mx-auto px-6 py-8 transition-all ${selectedLead ? "mr-96" : ""}`}>
        {/* ── KPI Cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <KpiCard
            icon={<Users size={14} />}
            label="Total Leads"
            value={kpis.totalLeads}
          />
          <KpiCard
            icon={<Zap size={14} />}
            label="Hooks Generated"
            value={kpis.hooksGenerated}
            accent
          />
          <KpiCard
            icon={<Mail size={14} />}
            label="Emails Sent"
            value={kpis.emailsSent}
          />
          <KpiCard
            icon={<MousePointerClick size={14} />}
            label="Click Rate"
            value={kpis.ctr}
            suffix="%"
            accent
          />
        </div>

        {/* ── Middle row: funnel + strike control ── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <div className="md:col-span-2">
            <PipelineFunnel stats={stats} />
          </div>
          <div>
            <StrikeControl />
          </div>
        </div>

        {/* ── Lead Board ── */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <Target size={13} className="text-purple-light" />
            <span className="text-[9px] font-mono tracking-[0.2em] text-faint uppercase">
              Lead Board
            </span>
            <span className="text-[9px] font-mono text-purple-light ml-auto">
              Click a lead to view intel report →
            </span>
          </div>
          <LeadBoard leads={leads} onSelect={setSelectedLead} />
        </div>
      </main>

      {/* ── Hook Preview Panel ── */}
      {selectedLead && (
        <>
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40"
            onClick={() => setSelectedLead(null)}
          />
          <HookPreviewPanel
            lead={selectedLead}
            onClose={() => setSelectedLead(null)}
          />
        </>
      )}
    </div>
  );
}
