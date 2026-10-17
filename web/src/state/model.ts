export type AnalysisStatus = 'succeeded' | 'queued' | 'running' | 'failed';
export type Entry = {
  id: string; entry_date: string; text: string; revision: number;
  analysis_status: AnalysisStatus; deleted?: boolean; analysis_message?: string;
};
export type Topic = { id: string; label: string; kind: string; x: number; y: number };
export type Mention = { entry_id: string; revision: number; topic_id: string; start: number; end: number; quote: string };
export type Node = Topic & { count: number; share: number | null; brightness: number; entry_ids: string[] };
export type Edge = { source: string; target: string; shared_entry_count: number; entry_ids: string[] };
export type Graph = { nodes: Node[]; edges: Edge[]; total_entries: number; analyzed_entries: number; pending_entries: number; failed_entries: number; scale: number };
export type Period = { from?: string; to?: string };

export function validDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))
    && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
}

export function inPeriod(entry: Entry, period: Period): boolean {
  return !entry.deleted && (!period.from || entry.entry_date >= period.from) && (!period.to || entry.entry_date < period.to);
}

export function aggregate(entries: Entry[], topics: Topic[], mentions: Mention[], period: Period = {}, scale?: number): Graph {
  const rows = entries.filter(e => inPeriod(e, period));
  const analyzed = rows.filter(e => e.analysis_status === 'succeeded');
  const memberships = new Map<string, Set<string>>();
  for (const e of analyzed) {
    memberships.set(e.id, new Set(mentions.filter(m => m.entry_id === e.id && m.revision === e.revision
      && m.start >= 0 && m.end > m.start && Array.from(e.text).slice(m.start, m.end).join('') === m.quote).map(m => m.topic_id)));
  }
  const counts = topics.map(t => ({ ...t, entry_ids: analyzed.filter(e => memberships.get(e.id)?.has(t.id)).map(e => e.id) }));
  const max = scale ?? Math.max(1, ...counts.map(t => t.entry_ids.length));
  const nodes = counts.map(t => ({ ...t, count: t.entry_ids.length, share: analyzed.length ? t.entry_ids.length / analyzed.length : null,
    brightness: t.entry_ids.length ? .25 + .75 * Math.log1p(t.entry_ids.length) / Math.log1p(max) : 0 }));
  const edges: Edge[] = [];
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const ids = analyzed.filter(e => memberships.get(e.id)?.has(nodes[i].id) && memberships.get(e.id)?.has(nodes[j].id)).map(e => e.id);
    if (ids.length) edges.push({ source: nodes[i].id, target: nodes[j].id, shared_entry_count: ids.length, entry_ids: ids });
  }
  return { nodes, edges, total_entries: rows.length, analyzed_entries: analyzed.length, scale: max,
    pending_entries: rows.filter(e => ['queued', 'running'].includes(e.analysis_status)).length,
    failed_entries: rows.filter(e => e.analysis_status === 'failed').length };
}

export function compare(entries: Entry[], topics: Topic[], mentions: Mention[], a: Period, b: Period) {
  const first = aggregate(entries, topics, mentions, a);
  const second = aggregate(entries, topics, mentions, b);
  const scale = Math.max(first.scale, second.scale);
  return { a: aggregate(entries, topics, mentions, a, scale), b: aggregate(entries, topics, mentions, b, scale) };
}

export function codePointExcerpt(text: string, start: number, end: number) {
  const points = Array.from(text);
  return { before: points.slice(0, start).join(''), quote: points.slice(start, end).join(''), after: points.slice(end).join('') };
}
