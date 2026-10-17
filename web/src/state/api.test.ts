import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MockJournalAPI, ConflictError } from './api.ts';

const data = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => data.get(key) ?? null,
  setItem: (key: string, value: string) => data.set(key, value),
  removeItem: (key: string) => data.delete(key),
} });

test('saving a new local entry never invents successful model analysis', async () => {
  data.clear(); const api = new MockJournalAPI();
  const entry = await api.commit('new', 'My own words.', '2026-10-17');
  assert.equal(entry.analysis_status, 'failed');
  assert.equal(api.graph().analyzed_entries, 5);
  assert.equal(api.graph().total_entries, 6);
});

test('editing an analyzed entry invalidates its old evidence immediately', async () => {
  data.clear(); const api = new MockJournalAPI();
  await api.commit('E1', 'I practiced guitar.', '2026-10-17', 1);
  assert.equal(api.graph().nodes.find(n => n.id === 'piano')?.count, 3);
  assert.equal(api.graph().edges.find(e => [e.source, e.target].sort().join('/') === 'friends/piano')?.shared_entry_count, 1);
});

test('cross-tab stale entry and draft versions fail visibly', async () => {
  data.clear(); const first = new MockJournalAPI(), second = new MockJournalAPI();
  await first.commit('E1', 'New version', '2026-10-17', 1);
  await assert.rejects(second.commit('E1', 'Stale text', '2026-10-17', 1), ConflictError);
  await first.saveDraft('draft', 0, 'Draft one', '2026-10-17');
  await assert.rejects(second.saveDraft('draft', 0, 'Conflicting draft', '2026-10-17'), ConflictError);
});

test('deletion removes co-mention evidence and persists across reload', () => {
  data.clear(); const api = new MockJournalAPI();
  api.deleteEntry('E3');
  assert.equal(api.graph().edges.some(e => e.source === 'home' || e.target === 'home'), false);
  assert.equal(new MockJournalAPI().entries.find(e => e.id === 'E3')?.deleted, true);
});
