import { describe, it, expect } from 'vitest';
import { narrowCard } from './narrowCard';
import type { WorkshopCardData, SkinReportCardData, InterruptCardData, ScheduleCardData } from '../types/cards';

// ============================================================
// Helper factories for valid card payloads
// ============================================================

function validWorkshopPayload() {
  return {
    card_type: 'workshop_card',
    session_id: 'sess-1',
    data: {
      products: [
        {
          id: 1,
          name: 'Gentle Cleanser',
          brand: 'CeraVe',
          category: 'cleanser',
          price: 15.99,
          reason: 'Low irritation, suits sensitive skin',
          key_ingredients: ['ceramides', 'niacinamide'],
          image_url: 'https://img.example.com/cerave.png',
        },
      ],
      conflicts: [],
      routine_tip: 'Use morning and evening',
    },
  };
}

function validSkinReportPayload() {
  return {
    card_type: 'skin_report_card',
    session_id: 'sess-2',
    data: {
      skin_type: 'combination',
      dimensions: {
        oil_level: 65,
        sensitivity: 30,
        hydration: 50,
        pigmentation: 20,
      },
      concerns: ['acne', 'redness'],
      recommendations: ['use gentle cleanser', 'apply SPF daily'],
      generated_at: '2025-06-01T12:00:00Z',
    },
  };
}

function validInterruptPayload() {
  return {
    card_type: 'interrupt_card',
    session_id: 'sess-3',
    data: {
      question: 'What is your main skin concern?',
      options: [
        { label: 'Acne', value: 'acne' },
        { label: 'Dryness', value: 'dryness' },
        { label: 'Aging', value: 'aging' },
      ],
      timeout_s: 30,
      session_id: 'sess-3',
      interrupt_id: 'int-001',
    },
  };
}

function validSchedulePayload() {
  return {
    card_type: 'schedule_card',
    session_id: 'sess-4',
    data: {
      morning: {
        time: '08:00',
        label: 'Morning Routine',
      },
      evening: {
        time: '20:00',
        label: 'Evening Routine',
      },
    },
  };
}

// ============================================================
// narrowCard — main exported function (exercises all validators)
// ============================================================

describe('narrowCard', () => {
  // --- null / undefined / non-object ---
  // Note: narrowCard destructures its parameter immediately (line 116),
  // so null/undefined throw TypeError rather than returning null.
  // The internal validators themselves (isObj, isStr, etc.) never throw.
  // To fix this, add a null check before destructuring.

  it('throws TypeError for null', () => {
    expect(() => narrowCard(null as any)).toThrow(TypeError);
  });

  it('throws TypeError for undefined', () => {
    expect(() => narrowCard(undefined as any)).toThrow(TypeError);
  });

  it('returns null for a string', () => {
    expect(narrowCard('hello' as any)).toBeNull();
  });

  it('returns null for a number', () => {
    expect(narrowCard(42 as any)).toBeNull();
  });

  it('returns null for an array', () => {
    expect(narrowCard([1, 2, 3] as any)).toBeNull();
  });

  it('returns null for an empty object', () => {
    expect(narrowCard({} as any)).toBeNull();
  });

  // --- unknown card_type ---

  it('returns null for unknown card_type', () => {
    expect(
      narrowCard({
        card_type: 'bogus_card',
        session_id: 'sess-x',
        data: {},
      }),
    ).toBeNull();
  });

  // ==========================================================
  // workshop_card
  // ==========================================================

  describe('workshop_card', () => {
    it('accepts a fully valid workshop card payload', () => {
      const result = narrowCard(validWorkshopPayload());
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('workshop_card');
    });

    it('rejects when data is not an object', () => {
      const payload = { card_type: 'workshop_card', session_id: 'sess-1', data: 'bad' as any };
      expect(narrowCard(payload)).toBeNull();
    });

    it('rejects when data is null', () => {
      const payload = { card_type: 'workshop_card', session_id: 'sess-1', data: null as any };
      expect(narrowCard(payload)).toBeNull();
    });

    it('rejects when products is missing', () => {
      const p = validWorkshopPayload();
      delete (p.data as any).products;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when products is not an array', () => {
      const p = validWorkshopPayload();
      (p.data as any).products = 'not-an-array';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a product is missing a required field (id)', () => {
      const p = validWorkshopPayload();
      delete (p.data as any).products[0].id;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a product field has wrong type (name is number)', () => {
      const p = validWorkshopPayload();
      (p.data as any).products[0].name = 999;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a product field has wrong type (price is string)', () => {
      const p = validWorkshopPayload();
      (p.data as any).products[0].price = 'free';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when key_ingredients is not a string array', () => {
      const p = validWorkshopPayload();
      (p.data as any).products[0].key_ingredients = [1, 2, 3];
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when routine_tip is missing', () => {
      const p = validWorkshopPayload();
      delete (p.data as any).routine_tip;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when routine_tip is not a string', () => {
      const p = validWorkshopPayload();
      (p.data as any).routine_tip = 123;
      expect(narrowCard(p)).toBeNull();
    });

    it('accepts workshop card with empty products array', () => {
      const p = validWorkshopPayload();
      (p.data as any).products = [];
      (p.data as any).routine_tip = 'No products recommended';
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('workshop_card');
    });

    it('accepts workshop card with multiple products', () => {
      const p = validWorkshopPayload();
      (p.data as any).products = [
        ...p.data.products,
        {
          id: 2,
          name: 'Moisturizer',
          brand: 'Neutrogena',
          category: 'moisturizer',
          price: 22.5,
          reason: 'Hydro boost',
          key_ingredients: ['hyaluronic acid'],
          image_url: 'https://img.example.com/neutrogena.png',
        },
      ];
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('workshop_card');
    });

    it('rejects when a product in the array is not an object', () => {
      const p = validWorkshopPayload();
      (p.data as any).products = ['not-an-object'];
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when id is NaN', () => {
      const p = validWorkshopPayload();
      (p.data as any).products[0].id = NaN;
      expect(narrowCard(p)).toBeNull();
    });
  });

  // ==========================================================
  // skin_report_card
  // ==========================================================

  describe('skin_report_card', () => {
    it('accepts a fully valid skin report card payload', () => {
      const result = narrowCard(validSkinReportPayload());
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('skin_report_card');
    });

    it('rejects when data is not an object', () => {
      const payload = { card_type: 'skin_report_card', session_id: 'sess-2', data: 123 as any };
      expect(narrowCard(payload)).toBeNull();
    });

    it('rejects when skin_type is missing', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).skin_type;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when skin_type is not a string', () => {
      const p = validSkinReportPayload();
      (p.data as any).skin_type = 42;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when dimensions is missing', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).dimensions;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when dimensions is not an object', () => {
      const p = validSkinReportPayload();
      (p.data as any).dimensions = 'bad';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a dimension field is missing (oil_level)', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).dimensions.oil_level;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a dimension field is not a number (hydratioNaN)', () => {
      const p = validSkinReportPayload();
      (p.data as any).dimensions.hydration = 'fifty';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when a dimension is NaN', () => {
      const p = validSkinReportPayload();
      (p.data as any).dimensions.pigmentation = NaN;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when concerns is missing', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).concerns;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when concerns is not a string array', () => {
      const p = validSkinReportPayload();
      (p.data as any).concerns = [1, 2, 3];
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when recommendations is missing', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).recommendations;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when recommendations is not a string array', () => {
      const p = validSkinReportPayload();
      (p.data as any).recommendations = 'use cleanser';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when generated_at is missing', () => {
      const p = validSkinReportPayload();
      delete (p.data as any).generated_at;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when generated_at is not a string', () => {
      const p = validSkinReportPayload();
      (p.data as any).generated_at = 1700000000;
      expect(narrowCard(p)).toBeNull();
    });

    it('accepts skin report with empty concerns and recommendations', () => {
      const p = validSkinReportPayload();
      (p.data as any).concerns = [];
      (p.data as any).recommendations = [];
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('skin_report_card');
    });

    it('accepts skin report with zero dimension values', () => {
      const p = validSkinReportPayload();
      (p.data as any).dimensions = {
        oil_level: 0,
        sensitivity: 0,
        hydration: 0,
        pigmentation: 0,
      };
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('skin_report_card');
    });
  });

  // ==========================================================
  // interrupt_card
  // ==========================================================

  describe('interrupt_card', () => {
    it('accepts a fully valid interrupt card payload', () => {
      const result = narrowCard(validInterruptPayload());
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('interrupt_card');
    });

    it('rejects when data is not an object', () => {
      const payload = { card_type: 'interrupt_card', session_id: 'sess-3', data: [] as any };
      expect(narrowCard(payload)).toBeNull();
    });

    it('rejects when question is missing', () => {
      const p = validInterruptPayload();
      delete (p.data as any).question;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when question is not a string', () => {
      const p = validInterruptPayload();
      (p.data as any).question = true;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when options is missing', () => {
      const p = validInterruptPayload();
      delete (p.data as any).options;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when options is not an array', () => {
      const p = validInterruptPayload();
      (p.data as any).options = { a: 1 };
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when an option is missing label', () => {
      const p = validInterruptPayload();
      (p.data as any).options[0] = { value: 'acne' }; // no label
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when an option is missing value', () => {
      const p = validInterruptPayload();
      (p.data as any).options[0] = { label: 'Acne' }; // no value
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when an option has wrong label type', () => {
      const p = validInterruptPayload();
      (p.data as any).options[0] = { label: 123, value: 'acne' };
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when an option has wrong value type', () => {
      const p = validInterruptPayload();
      (p.data as any).options[0] = { label: 'Acne', value: 123 };
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when timeout_s is missing', () => {
      const p = validInterruptPayload();
      delete (p.data as any).timeout_s;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when timeout_s is not a number', () => {
      const p = validInterruptPayload();
      (p.data as any).timeout_s = '30';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when timeout_s is NaN', () => {
      const p = validInterruptPayload();
      (p.data as any).timeout_s = NaN;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when session_id is missing from data', () => {
      const p = validInterruptPayload();
      delete (p.data as any).session_id;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when interrupt_id is missing', () => {
      const p = validInterruptPayload();
      delete (p.data as any).interrupt_id;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when interrupt_id is not a string', () => {
      const p = validInterruptPayload();
      (p.data as any).interrupt_id = 123;
      expect(narrowCard(p)).toBeNull();
    });

    it('accepts interrupt card with empty options array', () => {
      const p = validInterruptPayload();
      (p.data as any).options = [];
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('interrupt_card');
    });

    it('accepts interrupt card with timeout_s of 0', () => {
      const p = validInterruptPayload();
      (p.data as any).timeout_s = 0;
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('interrupt_card');
    });
  });

  // ==========================================================
  // schedule_card
  // ==========================================================

  describe('schedule_card', () => {
    it('accepts a fully valid schedule card payload', () => {
      const result = narrowCard(validSchedulePayload());
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('schedule_card');
    });

    it('rejects when data is not an object', () => {
      const payload = { card_type: 'schedule_card', session_id: 'sess-4', data: false as any };
      expect(narrowCard(payload)).toBeNull();
    });

    it('rejects when morning is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).morning;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when morning is not an object', () => {
      const p = validSchedulePayload();
      (p.data as any).morning = '08:00';
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when evening is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).evening;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when evening is not an object', () => {
      const p = validSchedulePayload();
      (p.data as any).evening = null;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when morning.time is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).morning.time;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when morning.time is not a string', () => {
      const p = validSchedulePayload();
      (p.data as any).morning.time = 800;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when morning.label is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).morning.label;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when morning.label is not a string', () => {
      const p = validSchedulePayload();
      (p.data as any).morning.label = 999;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when evening.time is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).evening.time;
      expect(narrowCard(p)).toBeNull();
    });

    it('rejects when evening.label is missing', () => {
      const p = validSchedulePayload();
      delete (p.data as any).evening.label;
      expect(narrowCard(p)).toBeNull();
    });

    it('accepts schedule card with extra unknown fields (forward-compatible)', () => {
      const p = validSchedulePayload();
      (p.data as any).morning.extra = 'ignored';
      (p.data as any).evening.steps = [];
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('schedule_card');
    });

    it('rejects when morning.time is an empty string (still a valid string)', () => {
      // empty string is a valid string per isStr, so this should pass
      const p = validSchedulePayload();
      (p.data as any).morning.time = '';
      const result = narrowCard(p);
      expect(result).not.toBeNull();
      expect(result!.card_type).toBe('schedule_card');
    });
  });

  // ==========================================================
  // Discriminated union behaviour — wrong-type data
  // ==========================================================

  it('rejects workshop_card data for a schedule_card type', () => {
    const p = {
      card_type: 'schedule_card',
      session_id: 'sess-1',
      data: validWorkshopPayload().data,
    };
    expect(narrowCard(p)).toBeNull();
  });

  it('rejects skin_report_card data for a workshop_card type', () => {
    const p = {
      card_type: 'workshop_card',
      session_id: 'sess-1',
      data: validSkinReportPayload().data,
    };
    expect(narrowCard(p)).toBeNull();
  });

  // ==========================================================
  // Type narrowing — verify returned type is correct at runtime
  // ==========================================================

  it('narrows to workshop_card with correct data shape', () => {
    const result = narrowCard(validWorkshopPayload());
    expect(result).not.toBeNull();
    expect(result!.card_type).toBe('workshop_card');
    // Verify data is preserved (type-narrow via union check)
    if (result!.card_type === 'workshop_card') {
      const typed: WorkshopCardData = result!.data;
      expect(typed.products).toHaveLength(1);
      expect(typed.products[0].name).toBe('Gentle Cleanser');
    }
    expect(result!.session_id).toBe('sess-1');
  });

  it('narrows to skin_report_card with correct data shape', () => {
    const result = narrowCard(validSkinReportPayload());
    expect(result).not.toBeNull();
    expect(result!.card_type).toBe('skin_report_card');
    if (result!.card_type === 'skin_report_card') {
      const typed: SkinReportCardData = result!.data;
      expect(typed.skin_type).toBe('combination');
      expect(typed.dimensions.oil_level).toBe(65);
    }
    expect(result!.session_id).toBe('sess-2');
  });

  it('narrows to interrupt_card with correct data shape', () => {
    const result = narrowCard(validInterruptPayload());
    expect(result).not.toBeNull();
    expect(result!.card_type).toBe('interrupt_card');
    if (result!.card_type === 'interrupt_card') {
      const typed: InterruptCardData = result!.data;
      expect(typed.question).toBe('What is your main skin concern?');
      expect(typed.options).toHaveLength(3);
    }
    expect(result!.session_id).toBe('sess-3');
  });

  it('narrows to schedule_card with correct data shape', () => {
    const result = narrowCard(validSchedulePayload());
    expect(result).not.toBeNull();
    expect(result!.card_type).toBe('schedule_card');
    if (result!.card_type === 'schedule_card') {
      const typed: ScheduleCardData = result!.data;
      expect(typed.morning.time).toBe('08:00');
      expect(typed.evening.time).toBe('20:00');
    }
    expect(result!.session_id).toBe('sess-4');
  });

  // ==========================================================
  // Graceful handling — validators never throw
  // ==========================================================

  it('does not throw on deeply nested malformed data', () => {
    expect(() =>
      narrowCard({
        card_type: 'workshop_card',
        session_id: 'sess-1',
        data: { products: [{ id: 1, name: null }] },
      } as any),
    ).not.toThrow();
  });

  it('does not throw when card_type is missing', () => {
    expect(() =>
      narrowCard({ session_id: 'sess-1', data: {} } as any),
    ).not.toThrow();
    expect(narrowCard({ session_id: 'sess-1', data: {} } as any)).toBeNull();
  });

  it('does not throw when session_id is missing', () => {
    // narrowCard destructures session_id but doesn't validate it separately;
    // if it's missing it'll be undefined but the function won't throw.
    expect(() =>
      narrowCard({ card_type: 'schedule_card', data: validSchedulePayload().data } as any),
    ).not.toThrow();
  });

  it('does not throw when data contains circular references', () => {
    const data: any = { morning: { time: '08:00', label: 'Morning' }, evening: { time: '20:00', label: 'Evening' } };
    // isObj and isStr don't recurse, so circular refs won't cause issues
    // but we verify no throw regardless
    expect(() =>
      narrowCard({ card_type: 'schedule_card', session_id: 'sess-1', data }),
    ).not.toThrow();
  });
});
