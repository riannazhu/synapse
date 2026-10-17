import { useEffect, useRef, useState } from 'react';
import type { MockJournalAPI } from './api';

/** Coalesce 800 ms edits, serialize saves, and flush before commit. */
export function useDraft(api: MockJournalAPI, id: string, text: string, date: string) {
  const [status, setStatus] = useState('Draft on this device');
  const version = useRef(api.restoreDraft(id)?.version ?? 0);
  const latest = useRef({ text, date });
  latest.current = { text, date };
  const saved = useRef('');
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const active = useRef(true);
  useEffect(() => () => { active.current = false; }, []);
  function flush() {
    const requested = { ...latest.current };
    const payload = JSON.stringify(requested);
    const save = async () => {
      if (saved.current === payload) return;
      if (active.current) setStatus('Saving draft…');
      version.current = await api.saveDraft(id, version.current, requested.text, requested.date);
      saved.current = payload;
      if (active.current) setStatus('Draft saved on this device');
    };
    chain.current = chain.current.then(save, save);
    return chain.current;
  }
  useEffect(() => {
    setStatus('Unsaved changes');
    const timer = setTimeout(() => { void flush().catch(() => {
      if (active.current) setStatus('Draft could not save. Your text is still in the editor.');
    }); }, 800);
    return () => clearTimeout(timer);
  }, [text, date, id]);
  return { status, flush };
}
