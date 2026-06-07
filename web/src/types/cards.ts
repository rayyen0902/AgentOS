export interface WorkshopProduct {
  id: number;
  name: string;
  brand: string;
  category: string;
  price: number;
  reason: string;
  key_ingredients: string[];
  image_url: string;
}

export interface WorkshopConflict {
  product_a: string;
  product_b: string;
  reason: string;
}

export interface WorkshopCardData {
  products: WorkshopProduct[];
  conflicts: WorkshopConflict[];
  routine_tip: string;
}

export interface SkinDimensions {
  oil_level: number;
  sensitivity: number;
  hydration: number;
  pigmentation: number;
}

export interface SkinReportCardData {
  skin_type: string;
  dimensions: SkinDimensions;
  concerns: string[];
  recommendations: string[];
  generated_at: string;
}

export interface InterruptCardData {
  question: string;
  options: string[];
  timeout_s: number;
}

export interface ScheduleStep {
  step: string;
  product: string;
  note?: string;
}

export interface ScheduleSlot {
  time: string;
  label: string;
  steps: ScheduleStep[];
  notes: string[];
}

export interface ScheduleCardData {
  morning: ScheduleSlot;
  evening: ScheduleSlot;
}

export type CardDataMap = {
  workshop_card: WorkshopCardData;
  skin_report_card: SkinReportCardData;
  interrupt_card: InterruptCardData;
  schedule_card: ScheduleCardData;
};
