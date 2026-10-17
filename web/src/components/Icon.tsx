const paths: Record<string, string> = {
  plus: 'M12 5v14M5 12h14', arrow: 'M5 12h14m-5-5 5 5-5 5', close: 'm6 6 12 12M6 18 18 6',
  home: 'm3 10 9-7 9 7v10H3Zm6 10v-7h6v7', book: 'M4 4h6l2 2 2-2h6v16h-6l-2 2-2-2H4Zm8 2v16',
  map: 'M6 5a2 2 0 1 0 0 .01M18 5a2 2 0 1 0 0 .01M12 18a2 2 0 1 0 0 .01M8 6h8M7 7l4 9m6-9-4 9',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z',
  pen: 'm15 4 5 5M4 20l1-6L16 3l5 5L10 19Z', mic: 'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',
  image: 'M3 4h18v16H3Zm0 12 5-5 5 5 3-3 5 5M14 8h.01', chat: 'M4 4h16v12H9l-5 4Z',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14m5 12 5 5', calendar: 'M4 5h16v16H4ZM8 2v6m8-6v6M4 10h16',
  check: 'm5 12 4 4L19 6', chevron: 'm9 5 7 7-7 7', pause: 'M8 5v14M16 5v14', play: 'm8 4 12 8-12 8Z',
  stop: 'M6 6h12v12H6Z', upload: 'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',
  trash: 'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',
  compare: 'M5 4v16m14-16v16M2 8h6m8 8h6M8 12h8', clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 4v5l3 2',
  leaf: 'M4 20c-2-10 3-16 16-16 0 13-6 18-16 16Zm0 0L15 9', rotate: 'M4 9a8 8 0 1 1 0 7M4 3v6h6',
};
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.spark} /></svg>;
}
