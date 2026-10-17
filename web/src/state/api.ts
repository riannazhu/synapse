/** Mock boundary for Track A. No provider key or live analysis runs in the browser. */
import journal from '../../../fixtures/demo_journal.json' with { type: 'json' };
import graphFixture from '../../../fixtures/generated/graph.json' with { type: 'json' };
import { aggregate, compare, type Entry, type Mention, type Period, type Topic, validDate } from './model.ts';

const STORE = 'synapse-demo-v1';
export const topics: Topic[] = graphFixture.nodes.map(({ id, label, kind, x, y }) => ({ id, label, kind, x, y }));
export const sampleEntries: Entry[] = journal.entries.map(e => ({ id: e.id, text: e.text, entry_date: e.entry_date,
  revision: e.revision, analysis_status: 'succeeded' }));
export const fixtureMentions: Mention[] = journal.entries.flatMap(e => e.extraction.topics.flatMap(t => t.evidence_spans.map(span => ({
  ...span, entry_id: e.id, revision: 1,
  topic_id: ({ 'Playing piano': 'piano', 'Piano practice': 'piano', Piano: 'piano', Friends: 'friends', Home: 'home' } as Record<string, string>)[t.label],
}))));
export const fixtureEvents = journal.entries.flatMap(e => e.extraction.events.map(event => ({ ...event, entry_id: e.id })));

export class ConflictError extends Error {}
type Draft = { text: string; entry_date: string; version: number };

function load(): Entry[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(STORE) || 'null');
    if (Array.isArray(saved) && saved.every(e => typeof e.id === 'string' && typeof e.text === 'string'
      && validDate(e.entry_date) && Number.isInteger(e.revision) && e.revision > 0
      && ['succeeded', 'failed', 'queued', 'running'].includes(e.analysis_status))) return saved;
  } catch { /* Corrupt or unavailable storage: start from the fictional sample. */ }
  return structuredClone(sampleEntries);
}

export class MockJournalAPI {
  entries = load();
  drafts = new Map<string, Draft>();
  onChange: (() => void) | undefined;
  private persist() {
    // Fail visibly if storage is unavailable; never claim a save succeeded.
    localStorage.setItem(STORE, JSON.stringify(this.entries));
    this.onChange?.();
  }
  mentions() {
    return fixtureMentions.filter(m => this.entries.some(e => e.id === m.entry_id && e.revision === m.revision
      && e.text === sampleEntries.find(seed => seed.id === e.id)?.text));
  }
  graph(period: Period = {}) {
    const all = aggregate(this.entries, topics, this.mentions());
    return aggregate(this.entries, topics, this.mentions(), period, all.scale);
  }
  comparison(a: Period, b: Period) { return compare(this.entries, topics, this.mentions(), a, b); }
  async saveDraft(id: string, expectedVersion: number, text: string, entry_date: string) {
    const raw = localStorage.getItem('synapse-draft-' + id);
    const old = raw ? JSON.parse(raw) as Draft : this.drafts.get(id);
    if ((old?.version ?? 0) !== expectedVersion) throw new ConflictError('This draft changed in another editor. Your text is still here.');
    if (!validDate(entry_date)) throw new Error('Choose a valid entry date.');
    const draft = { text, entry_date, version: expectedVersion + 1 };
    // Draft storage is distinct from approved entries and never enters the graph.
    localStorage.setItem('synapse-draft-' + id, JSON.stringify(draft));
    this.drafts.set(id, draft);
    return draft.version;
  }
  restoreDraft(id: string): Draft | undefined {
    if (this.drafts.has(id)) return this.drafts.get(id);
    try {
      const draft = JSON.parse(localStorage.getItem('synapse-draft-' + id) || 'null');
      if (draft && typeof draft.text === 'string' && validDate(draft.entry_date) && Number.isInteger(draft.version)) {
        this.drafts.set(id, draft); return draft;
      }
    } catch { /* Display a fresh editor if no valid draft is available. */ }
  }
  async commit(id: string, text: string, entry_date: string, expectedRevision?: number) {
    if (!text.trim() || text.length > 50000 || !validDate(entry_date)) throw new Error('Add text and a valid date before saving.');
    const current = load();
    const old = current.find(e => e.id === id);
    if (!old && expectedRevision !== undefined) throw new ConflictError('This entry was removed in another tab. Your draft is still available.');
    if (old && (old.deleted || old.revision !== expectedRevision)) throw new ConflictError('The saved entry changed. Copy your text before reloading.');
    const entry: Entry = { id, text, entry_date, revision: (old?.revision ?? 0) + 1,
      analysis_status: 'failed', analysis_message: 'Analysis is not connected in this browser demo. Your approved text is saved locally.' };
    const before = this.entries;
    this.entries = old ? current.map(e => e.id === id ? entry : e) : [entry, ...current];
    try { this.persist(); } catch (error) { this.entries = before; throw error; }
    this.drafts.delete(id);
    localStorage.removeItem('synapse-draft-' + id);
    return entry;
  }
  deleteEntry(id: string) {
    const before = this.entries;
    const current = load();
    if (current.find(e => e.id === id)?.revision !== before.find(e => e.id === id)?.revision) {
      throw new ConflictError('This entry changed in another tab. Reload before deleting.');
    }
    this.entries = current.map(e => e.id === id ? { ...e, deleted: true } : e);
    try { this.persist(); } catch (error) { this.entries = before; throw error; }
  }
  reset() {
    const before = this.entries;
    this.entries = structuredClone(sampleEntries);
    try { this.persist(); } catch (error) { this.entries = before; throw error; }
  }
}

export const sampleCapture = journal.capture;
