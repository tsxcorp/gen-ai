export type IconName = "image" | "upload" | "clipboard" | "file" | "close" | "check" | "chevron" | "sparkles" | "sliders" | "code" | "lock" | "settings" | "grid" | "ratio" | "video" | "shield" | "audio" | "download" | "edit" | "expand";

const paths: Record<IconName, string> = {
  image: "M4 4h16v16H4z M4 16l5-5 4 4 3-3 4 4 M15 8h.01",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5",
  clipboard: "M8 5H5v16h14V5h-3 M8 3h8v5H8z",
  file: "M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h5",
  close: "M6 6l12 12 M18 6L6 18", check: "M5 12l4 4L19 6", chevron: "M8 5l7 7-7 7",
  sparkles: "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  sliders: "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6",
  code: "M8 6l-6 6 6 6 M16 6l6 6-6 6 M14 3l-4 18",
  lock: "M5 10h14v11H5z M8 10V6a4 4 0 018 0v4",
  settings: "M9 3h6l1 4 4 2v6l-4 2-1 4H9l-1-4-4-2V9l4-2z M12 9a3 3 0 100 6 3 3 0 000-6",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  ratio: "M3 6h18v12H3z", video: "M3 5h12v14H3z M15 10l6-4v12l-6-4",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  audio: "M4 9h4l5-5v16l-5-5H4z M17 8a6 6 0 010 8 M20 5a10 10 0 010 14",
  download: "M12 3v13 M7 11l5 5 5-5 M4 17v4h16v-4",
  edit: "M14 5l5 5 M4 20l1-6L16 3l5 5L10 19z",
  expand: "M9 3H3v6 M15 3h6v6 M3 15v6h6 M21 15v6h-6",
};

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function RatioIcon({ value }: { value: string }) {
  const parts = value.split(/[:x×]/).map(Number);
  if (parts.length !== 2 || !parts.every((part) => Number.isFinite(part) && part > 0)) return <Icon name="sparkles" />;
  const scale = 18 / Math.max(...parts);
  const width = Math.max(3, (parts[0] ?? 1) * scale);
  const height = Math.max(3, (parts[1] ?? 1) * scale);
  return <svg className="icon ratio-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x={(24 - width) / 2} y={(24 - height) / 2} width={width} height={height} rx="2" /></svg>;
}
