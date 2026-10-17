import { useRef, useState } from 'react';
import { MockJournalAPI } from '../state/api';
import type { Entry } from '../state/model';
import { useDraft } from '../state/useDraft';
import { Dialog } from './Dialog';
import { Icon } from './Icon';
import { ChatCapture, HandwritingCapture, VoiceCapture } from './Capture';

export type Mode = 'write' | 'chat' | 'voice' | 'scan';
const MODES: { id: Mode; label: string; icon: string }[] = [{ id: 'write', label: 'Write', icon: 'pen' }, { id: 'chat', label: 'Chat', icon: 'chat' }, { id: 'voice', label: 'Voice memo', icon: 'mic' }, { id: 'scan', label: 'Handwriting', icon: 'image' }];
export function localToday() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; }

export function Composer({ api, entry, initialMode, onClose, onSaved }: { api: MockJournalAPI; entry?: Entry; initialMode: Mode; onClose: () => void; onSaved: () => void }) {
  const id = useRef(entry?.id || 'new-entry').current;
  const restored = useRef(api.restoreDraft(id)).current;
  const [text, setText] = useState(restored?.text ?? entry?.text ?? '');
  const [date, setDate] = useState(restored?.entry_date ?? entry?.entry_date ?? localToday());
  const [mode, setMode] = useState(initialMode);
  const [reviewRequired, setReviewRequired] = useState(false); const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const draft = useDraft(api, id, text, date);
  async function close() { try { await draft.flush(); onClose(); } catch { setError('Your draft could not be saved. Copy your text before closing.'); } }
  function addText(next: string) { setText(old => old.trim() ? old + '\n\n' + next : next); setReviewRequired(true); setReviewed(false); }
  async function save() {
    setBusy(true); setError('');
    try { await draft.flush(); await api.commit(entry?.id || crypto.randomUUID(), text, date, entry?.revision);
      if (!entry) { api.drafts.delete(id); localStorage.removeItem('synapse-draft-' + id); }
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save. Your text is still here.'); }
    finally { setBusy(false); }
  }
  return <Dialog title={entry ? 'Edit entry' : 'A little space for you'} wide onClose={() => { if (!busy) void close(); }}>
    <div className="composer-heading"><h2>{entry ? 'Make room for a new version.' : 'What’s on your mind?'}</h2><p>It doesn’t have to be extraordinary. It just has to be yours.</p></div>
    <div className="mode-picker" aria-label="Entry input method">{MODES.map(m => <button key={m.id} aria-pressed={mode === m.id} onClick={() => setMode(m.id)}><Icon name={m.icon} size={18} />{m.label}</button>)}</div>
    {mode === 'voice' && <VoiceCapture onText={addText} />}{mode === 'scan' && <HandwritingCapture onText={addText} />}{mode === 'chat' && <ChatCapture onText={addText} />}
    <div className="editor-meta"><label><Icon name="calendar" size={16} /><span className="sr-only">Entry date</span><input type="date" value={date} onChange={e => setDate(e.target.value)} required /></label><span role="status" className="small muted">{draft.status}</span></div>
    <label className="sr-only" htmlFor="entry-text">Approved journal text</label><textarea id="entry-text" className="entry-textarea" value={text} maxLength={50000} onChange={e => { setText(e.target.value); if (reviewRequired) setReviewed(false); }} placeholder="Start with a thought, a small moment, or something you’re still figuring out…" />
    <div className="editor-count">{text.length.toLocaleString()} / 50,000 characters</div>
    {reviewRequired && <label className="review-check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I’ve reviewed this text and want to include it in my entry.</label>}
    <p className="small muted">Demo saves stay in this browser. Audio, photos, and conversations are not attached. Live analysis is not connected.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="composer-footer"><button className="button" onClick={() => void close()} disabled={busy}>Keep draft & close</button><button className="button primary" onClick={() => void save()} disabled={busy || !text.trim() || !date || (reviewRequired && !reviewed)}>{busy ? 'Saving…' : 'Save entry'}<Icon name="arrow" size={17} /></button></div>
  </Dialog>;
}
