import { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle, Clock, Calendar, Target, ArrowRight } from 'lucide-react';

const PHASES = [
  {
    id: 'p0',
    name: 'Foundation',
    subtitle: 'Core Platform',
    status: 'complete',
    start: '2026-02-01',
    end: '2026-04-08',
    color: 'bg-emerald-500',
    milestones: [
      { name: 'Document Intake & Classification Engine', status: 'complete', date: '2026-02' },
      { name: 'Unified Queue (hub_documents)', status: 'complete', date: '2026-02' },
      { name: 'BC Integration (Read/Write)', status: 'complete', date: '2026-03' },
      { name: 'SharePoint Upload & Routing', status: 'complete', date: '2026-03' },
      { name: 'MS Graph Email Polling (AP)', status: 'complete', date: '2026-03' },
      { name: 'Vendor Matching & Alias Resolution', status: 'complete', date: '2026-03' },
      { name: 'Sales Module (legacy path)', status: 'complete', date: '2026-03' },
      { name: 'Shadow Pilot v1 Upload', status: 'complete', date: '2026-03' },
    ],
  },
  {
    id: 'p1',
    name: 'Phase 1',
    subtitle: 'AP Intelligence & Automation',
    status: 'complete',
    start: '2026-04-09',
    end: '2026-04-10',
    color: 'bg-blue-500',
    milestones: [
      { name: '20-Rule Force Cleanup Engine', status: 'complete', date: '2026-04-09' },
      { name: 'Exception Queue + 4x Retry System', status: 'complete', date: '2026-04-09' },
      { name: 'PO Auto-Retry Queue (park/retry/escalate)', status: 'complete', date: '2026-04-09' },
      { name: 'Inbox Metrics Panel', status: 'complete', date: '2026-04-09' },
      { name: 'Captured Doc Auto-Retry Scheduler', status: 'complete', date: '2026-04-09' },
      { name: 'ReadyForPost Auto-Post Scheduler', status: 'complete', date: '2026-04-10' },
      { name: 'Draft Auto-Approve (confidence-gated)', status: 'complete', date: '2026-04-10' },
      { name: 'Bulk Classify Endpoint + UI', status: 'complete', date: '2026-04-10' },
      { name: 'Freight Business Rules Engine', status: 'complete', date: '2026-04-10' },
      { name: 'Posted to BC Stats Widget', status: 'complete', date: '2026-04-10' },
      { name: '"Needs Review" Status-Readiness Mismatch Fix (270 docs)', status: 'complete', date: '2026-04-10' },
    ],
  },
  {
    id: 'p2',
    name: 'Phase 2',
    subtitle: 'Sales Order Governed Learning',
    status: 'complete',
    start: '2026-04-13',
    end: '2026-04-13',
    color: 'bg-violet-500',
    milestones: [
      { name: 'Sales Order Draft Context Service', status: 'complete', date: '2026-04-13' },
      { name: 'Feedback-to-Learning Pipeline', status: 'complete', date: '2026-04-13' },
      { name: 'Learning Suggestion Approval/Apply Workflow', status: 'complete', date: '2026-04-13' },
      { name: 'Learning Suggestions Admin UI', status: 'complete', date: '2026-04-13' },
      { name: 'Learning Impact Review Service', status: 'complete', date: '2026-04-13' },
      { name: 'Profile Drift & Change History Controls', status: 'complete', date: '2026-04-13' },
      { name: 'Customer Hotspot Review', status: 'complete', date: '2026-04-13' },
      { name: 'Maturity Checkpoint & Reusability Assessment', status: 'complete', date: '2026-04-13' },
      { name: 'Rep Overrides Management UI', status: 'complete', date: '2026-04-13' },
      { name: 'Evidence Threshold Tuning (drift-aware)', status: 'complete', date: '2026-04-13' },
    ],
  },
  {
    id: 'p3',
    name: 'Phase 3',
    subtitle: 'AP Invoice Advisory (3 sub-phases)',
    status: 'complete',
    start: '2026-04-13',
    end: '2026-04-14',
    color: 'bg-orange-500',
    milestones: [
      { name: 'P3a: AP Advisory Reviewer + Explainer + Feedback', status: 'complete', date: '2026-04-13' },
      { name: 'P3b: Disagreement Diagnostics + Confidence Calibration', status: 'complete', date: '2026-04-13' },
      { name: 'P3b: AP Learning Suggestions Generation', status: 'complete', date: '2026-04-13' },
      { name: 'P3c: Suggestion Approve/Reject/Apply Workflow', status: 'complete', date: '2026-04-14' },
      { name: 'P3c: Learning Impact Review', status: 'complete', date: '2026-04-14' },
      { name: 'P3c: Vendor Profile Drift Controls', status: 'complete', date: '2026-04-14' },
      { name: 'P3c: Vendor Hotspot Review', status: 'complete', date: '2026-04-14' },
      { name: 'Unified Governance Dashboard (ELT view)', status: 'complete', date: '2026-04-14' },
      { name: 'AP Advisory at parity with SO advisory', status: 'complete', date: '2026-04-14' },
    ],
  },
  {
    id: 'p4',
    name: 'Phase 4',
    subtitle: 'Inside Sales Pilot',
    status: 'active',
    start: '2026-04-14',
    end: '2026-04-15',
    color: 'bg-cyan-500',
    milestones: [
      { name: 'Pilot mailbox ingestion (3 ISRs)', status: 'complete', date: '2026-04-14' },
      { name: 'Relevance filtering (keywords + filename)', status: 'complete', date: '2026-04-14' },
      { name: 'Structured sales extraction + quality scoring', status: 'complete', date: '2026-04-14' },
      { name: 'BC Production cross-validation (read-only)', status: 'complete', date: '2026-04-14' },
      { name: 'Sales corpus validation (1000+ docs)', status: 'complete', date: '2026-04-15' },
      { name: 'Smart reclassifier (auto-tag non-sales)', status: 'complete', date: '2026-04-15' },
      { name: 'Pilot workflow guard (PilotReview status)', status: 'complete', date: '2026-04-15' },
      { name: 'Inside Sales Pilot dashboard tab', status: 'complete', date: '2026-04-15' },
      { name: 'Pilot data accumulation & learning', status: 'active', date: 'ongoing' },
    ],
  },
  {
    id: 'p5',
    name: 'Phase 5',
    subtitle: 'Teams Integration & Sales Automation',
    status: 'upcoming',
    start: '2026-04-16',
    end: '2026-04-30',
    color: 'bg-amber-500',
    milestones: [
      { name: 'Teams Adaptive Card webhook handler', status: 'upcoming', date: 'P1' },
      { name: 'Approve → BC Sales Order creation', status: 'upcoming', date: 'P1' },
      { name: 'Pilot Phase 2: enable SO creation for high-confidence docs', status: 'upcoming', date: 'P1' },
    ],
  },
  {
    id: 'p6',
    name: 'Phase 6',
    subtitle: 'Operations & Scale',
    status: 'future',
    start: '2026-05-01',
    end: '2026-06-30',
    color: 'bg-slate-500',
    milestones: [
      { name: 'Evergreen multi-PO container allocation spreadsheet', status: 'future', date: 'P2' },
      { name: 'BOL / Tracking No field storage in BC', status: 'future', date: 'P2' },
      { name: 'Low-volume vendor review routing (<5 docs)', status: 'future', date: 'P2' },
      { name: 'Email sender → vendor mapping', status: 'future', date: 'P2' },
      { name: 'Correction replay engine activation', status: 'future', date: 'P2' },
      { name: 'server.py modular extraction (8,500+ lines)', status: 'future', date: 'P3' },
    ],
  },
];

const STATUS_STYLES = {
  complete: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: 'Complete', icon: CheckCircle },
  active: { bg: 'bg-cyan-500/15', text: 'text-cyan-400', label: 'Active', icon: Clock },
  upcoming: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Upcoming', icon: Calendar },
  future: { bg: 'bg-slate-500/15', text: 'text-slate-400', label: 'Future', icon: Target },
};

const MILESTONE_DOT = {
  complete: 'bg-emerald-400',
  active: 'bg-cyan-400 animate-pulse',
  upcoming: 'bg-amber-400/60',
  future: 'bg-slate-500/40',
};

function PhaseRow({ phase, isExpanded, onToggle }) {
  const style = STATUS_STYLES[phase.status];
  const Icon = style.icon;
  const completedCount = phase.milestones.filter(m => m.status === 'complete').length;
  const totalCount = phase.milestones.length;
  const pct = Math.round((completedCount / totalCount) * 100);

  return (
    <div className="border border-border rounded-lg overflow-hidden" data-testid={`phase-${phase.id}`}>
      {/* Phase Header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-muted/30 transition-colors"
      >
        <div className={`w-1.5 h-12 rounded-full ${phase.color} flex-shrink-0`} />
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm">{phase.name}</span>
            <span className="text-xs text-muted-foreground">— {phase.subtitle}</span>
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-muted-foreground">{phase.start} → {phase.end}</span>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${style.bg} ${style.text} flex items-center gap-1`}>
              <Icon className="h-3 w-3" />{style.label}
            </span>
          </div>
        </div>
        {/* Progress bar */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="w-24 h-1.5 bg-muted rounded-full overflow-hidden">
            <div className={`h-full ${phase.color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
          </div>
          <span className="text-xs text-muted-foreground w-16 text-right">{completedCount}/{totalCount}</span>
        </div>
        {isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />}
      </button>

      {/* Milestones */}
      {isExpanded && (
        <div className="px-4 pb-3 pt-1 border-t border-border/50">
          <div className="space-y-1.5 ml-3">
            {phase.milestones.map((m, i) => (
              <div key={i} className="flex items-center gap-2.5 text-xs">
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${MILESTONE_DOT[m.status]}`} />
                <span className={m.status === 'complete' ? 'text-foreground' : 'text-muted-foreground'}>{m.name}</span>
                <span className="text-muted-foreground/60 ml-auto flex-shrink-0">{m.date}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function RoadmapGanttPage() {
  const [expanded, setExpanded] = useState(new Set(['p4', 'p5']));

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const totalMilestones = PHASES.reduce((s, p) => s + p.milestones.length, 0);
  const completedMilestones = PHASES.reduce((s, p) => s + p.milestones.filter(m => m.status === 'complete').length, 0);
  const overallPct = Math.round((completedMilestones / totalMilestones) * 100);
  const completedPhases = PHASES.filter(p => p.status === 'complete').length;
  const activePhases = PHASES.filter(p => p.status === 'active').length;

  return (
    <div className="space-y-6 max-w-5xl" data-testid="roadmap-gantt-page">
      {/* Header */}
      <div>
        <h2 className="text-lg font-bold tracking-tight">Build Roadmap</h2>
        <p className="text-sm text-muted-foreground">GPI Document Hub — development timeline and milestones</p>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-card border border-border rounded-lg p-3">
          <div className="text-xs text-muted-foreground">Overall Progress</div>
          <div className="text-2xl font-bold mt-0.5">{overallPct}%</div>
          <div className="h-1.5 bg-muted rounded-full mt-2 overflow-hidden">
            <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${overallPct}%` }} />
          </div>
        </div>
        <div className="bg-card border border-border rounded-lg p-3">
          <div className="text-xs text-muted-foreground">Milestones</div>
          <div className="text-2xl font-bold mt-0.5">{completedMilestones}<span className="text-sm font-normal text-muted-foreground">/{totalMilestones}</span></div>
        </div>
        <div className="bg-card border border-border rounded-lg p-3">
          <div className="text-xs text-muted-foreground">Phases Complete</div>
          <div className="text-2xl font-bold mt-0.5">{completedPhases}<span className="text-sm font-normal text-muted-foreground">/{PHASES.length}</span></div>
        </div>
        <div className="bg-card border border-border rounded-lg p-3">
          <div className="text-xs text-muted-foreground">Active Now</div>
          <div className="text-2xl font-bold mt-0.5 text-cyan-400">{activePhases} phase{activePhases !== 1 ? 's' : ''}</div>
        </div>
      </div>

      {/* Visual timeline bar */}
      <div className="bg-card border border-border rounded-lg p-4">
        <div className="text-xs text-muted-foreground mb-3">Timeline</div>
        <div className="flex gap-1 h-8 rounded-md overflow-hidden">
          {PHASES.map(p => {
            const width = p.status === 'future' ? 25 : p.status === 'upcoming' ? 15 : p.milestones.length * 2.5;
            return (
              <div
                key={p.id}
                className={`${p.color} ${p.status === 'future' ? 'opacity-30' : p.status === 'upcoming' ? 'opacity-50' : 'opacity-80'} rounded-sm relative group cursor-pointer`}
                style={{ flex: Math.max(width, 8) }}
                onClick={() => toggle(p.id)}
              >
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-[10px] font-bold text-white drop-shadow-sm truncate px-1">{p.name}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
          <span>Feb 2026</span>
          <span>Apr 9</span>
          <span>Apr 13</span>
          <span>Apr 14-15</span>
          <span>May</span>
          <span>Jun</span>
        </div>
      </div>

      {/* Phase list */}
      <div className="space-y-2">
        {PHASES.map(phase => (
          <PhaseRow
            key={phase.id}
            phase={phase}
            isExpanded={expanded.has(phase.id)}
            onToggle={() => toggle(phase.id)}
          />
        ))}
      </div>

      {/* Key decisions / next */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
          <ArrowRight className="h-4 w-4 text-amber-400" />
          Key Upcoming Decisions
        </h3>
        <div className="space-y-2 text-sm">
          <div className="flex items-start gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
            <span><strong>Pilot → Production:</strong> When Inside Sales Pilot data is sufficient, decide go/no-go on enabling SO auto-creation for high-confidence docs</span>
          </div>
          <div className="flex items-start gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
            <span><strong>Teams Integration:</strong> Finalize Adaptive Card payload format and approval flow with stakeholders</span>
          </div>
          <div className="flex items-start gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
            <span><strong>Scale:</strong> server.py modular extraction (8,500+ lines) — needed before adding more background services</span>
          </div>
        </div>
      </div>
    </div>
  );
}
