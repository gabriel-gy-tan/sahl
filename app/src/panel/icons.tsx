import {
  ArrowRight, ArrowUp, CaretDown, CaretLeft, CaretRight, CaretUp, ChatCircleText, Check, Copy, Cpu, CursorClick, GearSix,
  FileText, Folder, Globe, Heart, IdentificationBadge, IdentificationCard, Lightning, MagnifyingGlass, Microphone,
  PencilSimple, Plus, PuzzlePiece, Scales, ShieldCheck, SlidersHorizontal, SpeakerHigh, TextAa, Trash, User, WarningCircle, X,
  type Icon as Phosphor,
} from "@phosphor-icons/react";

// one set (Phosphor), one weight; the size comes from the stylesheet (.icon, 18 px unless a button says otherwise)
export const ICONS = {
  general: SlidersHorizontal,
  custom: TextAa,
  extension: PuzzlePiece,
  docs: FileText,
  telemetry: ShieldCheck,
  license: Scales,
  globe: Globe,
  pointer: CursorClick,
  user: User,
  chip: Cpu,
  speaker: SpeakerHigh,
  mic: Microphone,
  folder: Folder,
  trash: Trash,
  plus: Plus,
  bolt: Lightning,
  pencil: PencilSimple,
  passport: IdentificationBadge,
  card: IdentificationCard,
  chat: ChatCircleText,
  alert: WarningCircle,
  heart: Heart,
  search: MagnifyingGlass,
  copy: Copy,
  check: Check,
  send: ArrowUp,
  more: GearSix,
  close: X,
  up: CaretUp,
  down: CaretDown,
  back: CaretLeft,
  next: CaretRight,
  go: ArrowRight,
} satisfies Record<string, Phosphor>;

// these point along the reading direction, so they turn round in Arabic and Urdu
const FLIP = new Set<keyof typeof ICONS>(["back", "next", "go"]);

export function Icon({ name }: { name: keyof typeof ICONS }) {
  const Glyph = ICONS[name];
  return <Glyph className={FLIP.has(name) ? "icon flip" : "icon"} weight="regular" aria-hidden />;
}
