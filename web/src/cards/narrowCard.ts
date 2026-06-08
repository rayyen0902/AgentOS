import {
  WorkshopCardData,
  SkinReportCardData,
  InterruptCardData,
  ScheduleCardData,
  isCardType,
} from '../types/cards';

// ==== Zero-assertion runtime validators ====

function isStr(v: unknown): v is string {
  return typeof v === 'string';
}

function isNum(v: unknown): v is number {
  return typeof v === 'number' && !isNaN(v);
}

function isStrArr(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function field<T>(obj: unknown, key: string, guard: (v: unknown) => v is T): T | false {
  if (!isObj(obj)) return false;
  const val = obj[key];
  if (!guard(val)) return false;
  return val;
}

function validOptArr(arr: unknown, guard: (v: unknown) => boolean): boolean {
  return Array.isArray(arr) && arr.every(guard);
}

function labelValueGuard(v: unknown): boolean {
  return isObj(v) && isStr(v.label) && isStr(v.value);
}

// ==== Validators ====

function validWorkshopCard(data: unknown): data is WorkshopCardData {
  if (!isObj(data)) return false;
  const prods = field(data, 'products', Array.isArray);
  if (!prods) return false;
  for (const p of prods) {
    if (!isObj(p)) return false;
    if (!isNum(p.id)) return false;
    if (!isStr(p.name)) return false;
    if (!isStr(p.brand)) return false;
    if (!isStr(p.category)) return false;
    if (!isNum(p.price)) return false;
    if (!isStr(p.reason)) return false;
    if (!isStrArr(p.key_ingredients)) return false;
    if (!isStr(p.image_url)) return false;
  }
  const tip = field(data, 'routine_tip', isStr);
  if (tip === false) return false;
  return true;
}

function validSkinReport(data: unknown): data is SkinReportCardData {
  if (!isObj(data)) return false;
  if (!isStr(data.skin_type)) return false;
  const dims = field(data, 'dimensions', isObj);
  if (!dims) return false;
  if (!isNum(dims.oil_level)) return false;
  if (!isNum(dims.sensitivity)) return false;
  if (!isNum(dims.hydration)) return false;
  if (!isNum(dims.pigmentation)) return false;
  const concerns = field(data, 'concerns', isStrArr);
  if (!concerns) return false;
  const recs = field(data, 'recommendations', isStrArr);
  if (!recs) return false;
  const ts = field(data, 'generated_at', isStr);
  if (!ts) return false;
  return true;
}

function validInterruptCard(data: unknown): data is InterruptCardData {
  if (!isObj(data)) return false;
  if (!isStr(data.question)) return false;
  const opts = field(data, 'options', Array.isArray);
  if (!opts) return false;
  if (!validOptArr(opts, labelValueGuard)) return false;
  if (!isNum(data.timeout_s)) return false;
  if (!isStr(data.session_id)) return false;
  if (!isStr(data.interrupt_id)) return false;
  return true;
}

function validScheduleCard(data: unknown): data is ScheduleCardData {
  if (!isObj(data)) return false;
  const morning = field(data, 'morning', isObj);
  if (!morning) return false;
  const evening = field(data, 'evening', isObj);
  if (!evening) return false;
  if (!isStr(morning.time)) return false;
  if (!isStr(morning.label)) return false;
  if (!isStr(evening.time)) return false;
  if (!isStr(evening.label)) return false;
  return true;
}

// ==== Typed discriminated union ====

export type TypedCard =
  | { card_type: 'workshop_card'; data: WorkshopCardData; session_id: string }
  | { card_type: 'skin_report_card'; data: SkinReportCardData; session_id: string }
  | { card_type: 'interrupt_card'; data: InterruptCardData; session_id: string }
  | { card_type: 'schedule_card'; data: ScheduleCardData; session_id: string };

export function narrowCard(raw: { card_type: string; data: Record<string, unknown>; session_id: string }): TypedCard | null {
  const { card_type, data, session_id } = raw;

  if (isCardType(card_type, 'workshop_card') && validWorkshopCard(data)) {
    return { card_type: 'workshop_card', data, session_id };
  }
  if (isCardType(card_type, 'skin_report_card') && validSkinReport(data)) {
    return { card_type: 'skin_report_card', data, session_id };
  }
  if (isCardType(card_type, 'interrupt_card') && validInterruptCard(data)) {
    return { card_type: 'interrupt_card', data, session_id };
  }
  if (isCardType(card_type, 'schedule_card') && validScheduleCard(data)) {
    return { card_type: 'schedule_card', data, session_id };
  }
  return null;
}
