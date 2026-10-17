import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { aggregate, codePointExcerpt, compare, validDate, type Entry, type Mention, type Topic } from './model.ts';

const topics: Topic[] = ['piano', 'friends', 'home'].map((id, i) => ({ id, label: id, kind: 'topic', x: i*.2, y: .4 }));
const entries: Entry[] = [
  { id: 'E1', text: 'piano friends', revision: 1, entry_date: '2025-01-01', analysis_status: 'succeeded' },
  { id: 'E2', text: 'piano', revision: 1, entry_date: '2025-02-01', analysis_status: 'succeeded' },
  { id: 'E3', text: 'friends home', revision: 1, entry_date: '2026-01-01', analysis_status: 'succeeded' },
];
const mentions: Mention[] = entries.flatMap(e => e.text.split(' ').map(word => ({ entry_id: e.id, revision: 1, topic_id: word, start: e.text.indexOf(word), end: e.text.indexOf(word)+word.length, quote: word })));

test('distinct-entry counts and edges match the LLD fixture', () => {
  const graph = aggregate(entries, topics, [...mentions, mentions[0]]);
  assert.deepEqual(graph.nodes.map(n => n.count), [2, 2, 1]);
  assert.deepEqual(graph.edges.map(e => [e.source, e.target, e.shared_entry_count]), [['piano', 'friends', 1], ['friends', 'home', 1]]);
});

test('new revisions, tombstones, and invalid quotes remove old graph evidence', () => {
  const edited = entries.map(e => e.id === 'E1' ? { ...e, revision: 2 } : e);
  assert.deepEqual(aggregate(edited, topics, mentions).nodes.map(n => n.count), [1, 1, 1]);
  assert.deepEqual(aggregate(entries.map(e => ({ ...e, deleted: true })), topics, mentions).nodes.map(n => n.share), [null, null, null]);
  assert.equal(aggregate(entries, topics, mentions.map(m => ({ ...m, quote: 'fabricated' }))).edges.length, 0);
});

test('date bounds are half-open and empty periods preserve coordinates', () => {
  const graph = aggregate(entries, topics, mentions, { from: '2025-01-01', to: '2026-01-01' });
  assert.equal(graph.total_entries, 2);
  assert.deepEqual(graph.nodes.map(n => [n.x, n.y]), topics.map(n => [n.x, n.y]));
});

test('comparison uses one scale and analyzed entries are the denominator', () => {
  const result = compare([...entries, { ...entries[0], id: 'pending', analysis_status: 'queued' }], topics, mentions,
    { from: '2025-01-01', to: '2026-01-01' }, { from: '2026-01-01', to: '2027-01-01' });
  assert.equal(result.a.scale, result.b.scale);
  assert.equal(result.a.nodes[0].share, 1);
  assert.equal(result.a.total_entries, 3);
  assert.equal(result.a.analyzed_entries, 2);
  assert.equal(result.a.pending_entries, 1);
});

test('highlight offsets use Unicode code points', () => {
  assert.deepEqual(codePointExcerpt('🎹 piano', 2, 7), { before: '🎹 ', quote: 'piano', after: '' });
});

test('invalid calendar dates are rejected', () => {
  assert.equal(validDate('2026-02-30'), false);
  assert.equal(validDate('2026-10-17'), true);
});

test('mock graph matches the Python-generated five-entry fixture', async () => {
  const { sampleEntries, topics: seedTopics, fixtureMentions } = await import('./api.ts');
  const expected = JSON.parse(readFileSync(new URL('../../../fixtures/generated/graph.json', import.meta.url), 'utf8'));
  const result = aggregate(sampleEntries, seedTopics, fixtureMentions);
  assert.deepEqual(result.nodes.map(n => [n.id, n.count, n.share]), expected.nodes.map((n: { id: string; count: number; share: number }) => [n.id, n.count, n.share]));
  const normalize = (edges: { source: string; target: string; shared_entry_count: number }[]) => edges.map(e => [e.source, e.target].sort().join('/')+':'+e.shared_entry_count).sort();
  assert.deepEqual(normalize(result.edges), normalize(expected.edges));
});
