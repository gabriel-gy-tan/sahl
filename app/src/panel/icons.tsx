// line icons on a 24 grid, drawn like the mic and speaker
export const ICONS = {
  general: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  custom: "M4 7V4h16v3M9 20h6M12 4v16",
  extension: "M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1L11 5M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1L13 19",
  docs: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5",
  telemetry: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
  license: "M12 3v18M7 21h10M4 7h16M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0z",
  globe: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18",
  pointer: "M9 9l5 12 1.8-5.2L21 14zM7.2 2.2L8 5.1M5.1 8l-2.9-.8M14 4.1L12 6M6 12l-1.9 2",
  user: "M12 12a4 4 0 1 0 0-8a4 4 0 1 0 0 8M4 21a8 8 0 0 1 16 0",
  chip: "M7 7h10v10H7zM10 10h4v4h-4zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3",
  speaker: "M4 9.5h3.5L12 5.5v13l-4.5-4H4zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
  folder: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  trash: "M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6",
  plus: "M12 5v14M5 12h14",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  pencil: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
  passport: "M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1M12 8.5a3 3 0 1 0 0 6a3 3 0 1 0 0-6M9 17.5h6",
  card: "M3 6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM8 8.5a2 2 0 1 0 0 4a2 2 0 1 0 0-4M5.5 16.5c.6-1.8 4.4-1.8 5 0M13 10h5M13 14h4",
  chat: "M4 5h16v11H9l-5 4z",
  alert: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 8v5M12 16v.5",
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
} as const;
export function Icon({ name }: { name: keyof typeof ICONS }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden><path d={ICONS[name]} /></svg>;
}
