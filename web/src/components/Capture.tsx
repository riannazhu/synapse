import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { sampleCapture } from '../state/api';

export function VoiceCapture({ onText }: { onText: (text: string) => void }) {
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const [state, setState] = useState('idle');
  const [audio, setAudio] = useState<Blob | null>(null);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; if (recorder.current?.state !== 'inactive') recorder.current?.stop(); stream.current?.getTracks().forEach(t => t.stop()); }, []);
  useEffect(() => {
    if (!audio) return;
    const next = URL.createObjectURL(audio); setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [audio]);
  async function record() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setError('Recording is unavailable in this browser. You can upload an audio file instead.'); return; }
    setState('permission'); setError('');
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!alive.current) { media.getTracks().forEach(t => t.stop()); return; }
      stream.current = media;
      const chunks: Blob[] = [];
      const next = new MediaRecorder(media); recorder.current = next;
      next.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      next.onstop = () => {
        media.getTracks().forEach(t => t.stop());
        if (alive.current) { setAudio(new Blob(chunks, { type: next.mimeType })); setState('ready'); }
      };
      next.onerror = () => { media.getTracks().forEach(t => t.stop()); if (alive.current) { setState('idle'); setError('Recording stopped unexpectedly. Try again or upload a file.'); } };
      next.start(); setState('recording');
    } catch { if (alive.current) { setState('idle'); setError('Microphone access was not granted. You can upload a file or write instead.'); } }
  }
  return <div className="capture-box">
    <div className={'capture-symbol ' + (state === 'recording' ? 'recording' : '')}><Icon name="mic" size={29} /></div>
    <h3>{state === 'recording' ? 'Take your time. We’re listening.' : state === 'paused' ? 'A moment to pause.' : 'Say what’s on your mind.'}</h3>
    <p>Record a thought or upload a voice memo. You’ll review the words before saving.</p>
    <div className="capture-actions">
      {['idle', 'ready'].includes(state) && <button className="button primary" onClick={() => void record()}><Icon name="mic" size={17} />{audio ? 'Record again' : 'Start recording'}</button>}
      {state === 'permission' && <span role="status">Waiting for microphone permission…</span>}
      {['recording', 'paused'].includes(state) && <><button className="button" onClick={() => {
        if (state === 'paused') { recorder.current?.resume(); setState('recording'); } else { recorder.current?.pause(); setState('paused'); }
      }}><Icon name={state === 'paused' ? 'play' : 'pause'} size={16} />{state === 'paused' ? 'Resume' : 'Pause'}</button><button className="button" onClick={() => recorder.current?.stop()}><Icon name="stop" size={16} />Stop</button></>}
      <label className="button file-label"><Icon name="upload" size={16} />Upload audio<input type="file" accept="audio/mpeg,audio/mp4,audio/wav,audio/webm,audio/x-m4a" onChange={e => {
        const file = e.target.files?.[0]; if (!file) return;
        if (file.size > 25_000_000) { setError('Choose an audio file smaller than 25 MB.'); return; }
        setAudio(file); setState('ready'); setError('');
      }} /></label>
    </div>
    {url && <div className="audio-review"><audio controls src={url} onLoadedMetadata={e => { if (e.currentTarget.duration > 900) setError('This recording exceeds 15 minutes. Choose a shorter one.'); }} /><p>This recording is available for playback only. Transcription and attachment storage are not connected; add your text below.</p></div>}
    {error && <p role="alert" className="error">{error}</p>}
    <button className="text-button" onClick={() => onText(sampleCapture.audio_text)}>Try a fictional sample transcript <Icon name="arrow" size={15} /></button>
  </div>;
}

function PagePreview({ file, index, onRemove, onMove }: { file: File; index: number; onRemove: () => void; onMove: (by: number) => void }) {
  const [url, setUrl] = useState(''); const [rotation, setRotation] = useState(0);
  useEffect(() => { const next = URL.createObjectURL(file); setUrl(next); return () => URL.revokeObjectURL(next); }, [file]);
  return <div className="page-preview"><div className="page-image"><img src={url} style={{ transform: `rotate(${rotation}deg)` }} alt={`Handwritten page ${index+1}`} /></div><span>Page {index+1}</span><div className="page-tools"><button aria-label={`Move page ${index+1} earlier`} disabled={index === 0} onClick={() => onMove(-1)}>←</button><button aria-label={`Move page ${index+1} later`} onClick={() => onMove(1)}>→</button><button title="Rotate preview" aria-label={`Rotate preview for page ${index+1}`} onClick={() => setRotation(r => r+90)}><Icon name="rotate" size={15} /></button><button aria-label={`Remove page ${index+1}`} onClick={onRemove}><Icon name="trash" size={15} /></button></div></div>;
}

export function HandwritingCapture({ onText }: { onText: (text: string) => void }) {
  const [files, setFiles] = useState<File[]>([]); const [error, setError] = useState('');
  const [sample, setSample] = useState(false);
  function choose(next: FileList | null) {
    if (!next) return;
    const selected = Array.from(next);
    if (files.length + selected.length > 10 || selected.some(f => f.size > 10_000_000 || !['image/jpeg', 'image/png'].includes(f.type))) { setError('Use up to 10 JPEG or PNG pages, each under 10 MB.'); return; }
    setFiles(old => [...old, ...selected]); setError('');
  }
  return <div className="capture-box"><div className="capture-symbol"><Icon name="image" size={28} /></div><h3>A page from your world.</h3><p>Bring your handwriting into your journal. Keep the original beside your words.</p>
    <div className="capture-actions"><label className="button primary file-label"><Icon name="upload" size={16} />Choose pages<input type="file" multiple accept="image/jpeg,image/png" onChange={e => choose(e.target.files)} /></label><label className="button file-label">Take a photo<input type="file" accept="image/jpeg,image/png" capture="environment" onChange={e => choose(e.target.files)} /></label></div>
    {files.length > 0 && <><div className="page-grid">{files.map((file, i) => <PagePreview key={file.name+file.lastModified+i} file={file} index={i} onRemove={() => setFiles(old => old.filter((_, j) => i !== j))} onMove={by => setFiles(old => {
      const next = [...old], to = i+by; if (to >= 0 && to < next.length) [next[i], next[to]] = [next[to], next[i]]; return next;
    })} />)}</div><p>These previews are not uploaded or retained. Extraction is not connected; transcribe the text below. Crop or retake photos in your camera app.</p></>}
    {sample && <div className="sample-paper"><span>FICTIONAL HANDWRITING SAMPLE</span><p>I want to learn piano.<br />I talked with friends about piano.</p></div>}
    {error && <p className="error" role="alert">{error}</p>}
    <button className="text-button" onClick={() => { setSample(true); onText(sampleCapture.page_text); }}>Try a fictional handwritten entry <Icon name="arrow" size={15} /></button>
  </div>;
}

export function ChatCapture({ onText }: { onText: (text: string) => void }) {
  const [messages, setMessages] = useState<{ role: string; text: string }[]>([{ role: 'assistant', text: 'What has been on your mind lately?' }]);
  const [input, setInput] = useState('');
  function send() {
    if (!input.trim()) return;
    setMessages(old => [...old, { role: 'user', text: input.trim() }, { role: 'assistant', text: 'What feels most important about that to you?' }]); setInput('');
  }
  return <div className="chat-capture"><div className="chat-note"><Icon name="spark" size={15} /> Scripted demo conversation · journal history is off</div><div className="chat-messages" aria-live="polite">{messages.map((m, i) => <div key={i} className={'bubble ' + m.role}>{m.role === 'assistant' && <span className="bubble-label">SYNAPSE</span>}{m.text}</div>)}</div><div className="chat-input"><label className="sr-only" htmlFor="chat-input">Your message</label><input id="chat-input" value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} placeholder="Start wherever you are…" maxLength={4000} /><button className="icon-button" disabled={!input.trim()} onClick={send} aria-label="Send message"><Icon name="arrow" /></button></div><button className="button" disabled={!messages.some(m => m.role === 'user')} onClick={() => onText(messages.filter(m => m.role === 'user').map(m => m.text).join('\n\n'))}>Finish and review my words <Icon name="arrow" size={16} /></button><p className="small muted">This demo copies your statements into an editable draft. Assistant replies are excluded. The conversation is not retained after you close this editor.</p></div>;
}
