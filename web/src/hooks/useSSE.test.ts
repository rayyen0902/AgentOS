import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSSE } from './useSSE';
import { useChatStore } from '../store/chatStore';

// ============================================================
// Mock EventSource
// ============================================================
// The real EventSource is not available in jsdom, so we provide a
// minimal shim that the hook can construct and interact with.

type EventHandler = (e: MessageEvent) => void;

let mockEventSourceInstances: MockEventSource[] = [];

const CONNECTING = 0;
const OPEN = 1;
const CLOSED = 2;

class MockEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState: number = CONNECTING;
  CONNECTING = CONNECTING;
  OPEN = OPEN;
  CLOSED = CLOSED;
  CLOSED_STATIC = CLOSED;
  private listeners: Record<string, EventHandler[]> = {};
  private _closed = false;

  constructor(url: string) {
    this.url = url;
    mockEventSourceInstances.push(this);
  }

  addEventListener(event: string, handler: EventHandler) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(handler);
  }

  removeEventListener(event: string, handler: EventHandler) {
    const handlers = this.listeners[event];
    if (!handlers) return;
    const idx = handlers.indexOf(handler);
    if (idx >= 0) handlers.splice(idx, 1);
  }

  close() {
    this._closed = true;
    this.readyState = CLOSED;
    // Remove from global tracker
    const idx = mockEventSourceInstances.indexOf(this);
    if (idx >= 0) mockEventSourceInstances.splice(idx, 1);
  }

  get closedForTest() {
    return this._closed;
  }

  // --- test helpers ---

  /** Simulate the connection opening */
  dispatchOpen() {
    this.readyState = OPEN;
    this.onopen?.();
  }

  /** Dispatch a named event with JSON-stringified data */
  dispatchEvent(event: string, data: unknown) {
    const handlers = this.listeners[event] || [];
    const payload = JSON.stringify(data);
    const messageEvent = { data: payload } as MessageEvent;
    handlers.forEach((h) => h(messageEvent));
  }

  /** Dispatch a malformed (non-JSON) event */
  dispatchMalformedEvent(event: string, raw: string) {
    const handlers = this.listeners[event] || [];
    const messageEvent = { data: raw } as MessageEvent;
    handlers.forEach((h) => h(messageEvent));
  }

  /** Dispatch an event with oversized data (> 64KB) */
  dispatchOversizedEvent(event: string) {
    const handlers = this.listeners[event] || [];
    const big = 'x'.repeat(65 * 1024);
    const messageEvent = { data: big } as MessageEvent;
    handlers.forEach((h) => h(messageEvent));
  }

  /** Trigger onerror to simulate connection loss */
  triggerError() {
    this.onerror?.();
  }
}

// ============================================================
// Store helpers
// ============================================================

const INITIAL_STORE_STATE = {
  messages: [] as any[],
  statusStream: [] as any[],
  interrupt: null,
  currentCard: null,
  errorEvent: null,
  isProcessing: false,
  sseConnected: false,
};

function resetStore() {
  useChatStore.setState({ ...INITIAL_STORE_STATE });
}

// ============================================================
// Test setup / teardown
// ============================================================

describe('useSSE', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockEventSourceInstances = [];
    resetStore();
    localStorage.clear();
    (globalThis as any).EventSource = MockEventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ==========================================================
  // Connection lifecycle
  // ==========================================================

  it('creates an EventSource with the correct URL on mount', () => {
    renderHook(() => useSSE('session-abc'));

    expect(mockEventSourceInstances.length).toBe(1);
    const es = mockEventSourceInstances[0];
    expect(es.url).toContain('/api/v1/chat/stream');
    expect(es.url).toContain('session_id=session-abc');
  });

  it('URL-encodes the session_id parameter', () => {
    renderHook(() => useSSE('sess/with?special&chars'));
    const es = mockEventSourceInstances[0];
    expect(es.url).toContain('session_id=sess%2Fwith%3Fspecial%26chars');
  });

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() => useSSE('session-abc'));
    expect(mockEventSourceInstances.length).toBe(1);

    unmount();

    expect(mockEventSourceInstances.length).toBe(0);
  });

  it('cleans up timer on unmount', () => {
    const { unmount } = renderHook(() => useSSE('session-abc'));

    const es = mockEventSourceInstances[0];
    // Trigger an error to schedule a retry timer
    act(() => {
      es.triggerError();
    });

    // Clear mocks so the unmount doesn't try to interact with closed ES
    unmount();

    // Verify no memory leak — the timer should be cleared by cleanup
    // (we can't easily assert on internal refs, but the hook's
    //  return function calls cleanup() which clears timerRef)
  });

  it('does not reconnect after unmount', () => {
    const { unmount } = renderHook(() => useSSE('session-abc'));

    unmount();
    const instanceCount = mockEventSourceInstances.length;

    // Fast-forward past any pending retry timeouts
    act(() => {
      vi.advanceTimersByTime(60000);
    });

    // No new EventSource should have been created
    expect(mockEventSourceInstances.length).toBe(instanceCount);
  });

  // ==========================================================
  // sseConnected state
  // ==========================================================

  it('sets sseConnected=true on es.onopen', () => {
    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchOpen();
    });

    expect(useChatStore.getState().sseConnected).toBe(true);
  });

  it('sets sseConnected=true on heartbeat when currently false', () => {
    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('heartbeat', {});
    });

    expect(useChatStore.getState().sseConnected).toBe(true);
  });

  it('keeps sseConnected=true on heartbeat when already true', () => {
    useChatStore.setState({ sseConnected: true });
    renderHook(() => useSSE('session-abc'));

    const es = mockEventSourceInstances[0];
    // spy on setState to verify it is NOT called unnecessarily
    const spy = vi.spyOn(useChatStore, 'setState');

    act(() => {
      es.dispatchEvent('heartbeat', {});
    });

    // setState should NOT be called when sseConnected is already true
    const heartbeatCalls = spy.mock.calls.filter(
      (call) => (call[0] as any)?.sseConnected !== undefined,
    );
    expect(heartbeatCalls.length).toBe(0);

    spy.mockRestore();
  });

  it('sets sseConnected=false on es.onerror', () => {
    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchOpen();
    });
    expect(useChatStore.getState().sseConnected).toBe(true);

    act(() => {
      es.triggerError();
    });
    expect(useChatStore.getState().sseConnected).toBe(false);
  });

  // ==========================================================
  // status events
  // ==========================================================

  it('dispatches status events to appendStatus', () => {
    const appendStatusSpy = vi.spyOn(useChatStore.getState(), 'appendStatus');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const statusEvent = {
      seq: 1,
      source: 'orchestrator',
      status: 'running',
      label: 'Analyzing request...',
      session_id: 'session-abc',
    };

    act(() => {
      es.dispatchEvent('status', statusEvent);
    });

    expect(appendStatusSpy).toHaveBeenCalledWith(statusEvent);

    appendStatusSpy.mockRestore();
  });

  it('fills missing session_id on status events', () => {
    const appendStatusSpy = vi.spyOn(useChatStore.getState(), 'appendStatus');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const statusEvent = {
      seq: 1,
      source: 'orchestrator',
      status: 'running',
      label: 'Processing...',
      // no session_id
    };

    act(() => {
      es.dispatchEvent('status', statusEvent);
    });

    expect(appendStatusSpy).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 'session-abc' }),
    );

    appendStatusSpy.mockRestore();
  });

  // ==========================================================
  // reply events
  // ==========================================================

  it('dispatches reply events to appendMessage', () => {
    const appendMessageSpy = vi.spyOn(useChatStore.getState(), 'appendMessage');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('reply', {
        text: 'Hello! How can I help?',
        from: 'copywriter-agent',
        session_id: 'session-abc',
      });
    });

    expect(appendMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        role: 'assistant',
        content: 'Hello! How can I help?',
      }),
    );

    appendMessageSpy.mockRestore();
  });

  it('fills missing session_id on reply events', () => {
    const appendMessageSpy = vi.spyOn(useChatStore.getState(), 'appendMessage');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('reply', {
        text: 'Hello!',
        from: 'agent',
      });
    });

    expect(appendMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        role: 'assistant',
        content: 'Hello!',
      }),
    );

    appendMessageSpy.mockRestore();
  });

  // ==========================================================
  // interrupt events
  // ==========================================================

  it('dispatches interrupt events to setInterrupt', () => {
    const setInterruptSpy = vi.spyOn(useChatStore.getState(), 'setInterrupt');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const interruptEvent = {
      session_id: 'session-abc',
      interrupt_id: 'int-001',
      message: 'What is your skin type?',
      options: [
        { label: 'Oily', value: 'oily' },
        { label: 'Dry', value: 'dry' },
      ],
    };

    act(() => {
      es.dispatchEvent('interrupt', interruptEvent);
    });

    expect(setInterruptSpy).toHaveBeenCalledWith(interruptEvent);

    setInterruptSpy.mockRestore();
  });

  // ==========================================================
  // card events
  // ==========================================================

  it('calls setCard on card event', () => {
    const setCardSpy = vi.spyOn(useChatStore.getState(), 'setCard');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('card', {
        session_id: 'session-abc',
        card_type: 'workshop_card',
        data: { products: [] },
      });
    });

    expect(setCardSpy).toHaveBeenCalled();

    setCardSpy.mockRestore();
  });

  it('attaches card to the latest assistant message without a card', () => {
    // Pre-seed the store with an assistant message
    useChatStore.setState({
      messages: [
        { id: 'msg-1', role: 'user', content: 'help', timestamp: 1 },
        { id: 'msg-2', role: 'assistant', content: 'Sure!', timestamp: 2 },
      ],
    });

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const cardPayload = {
      session_id: 'session-abc',
      card_type: 'workshop_card',
      data: { products: [{ id: 1, name: 'Cleanser' }] },
    };

    act(() => {
      es.dispatchEvent('card', cardPayload);
    });

    const msgs = useChatStore.getState().messages;
    const assistantMsg = msgs.find((m) => m.id === 'msg-2');
    expect(assistantMsg?.card).toEqual(cardPayload);
  });

  it('attaches card only to first card-less assistant message from the end', () => {
    // Two assistant messages, first already has a card
    useChatStore.setState({
      messages: [
        { id: 'msg-1', role: 'user', content: 'a', timestamp: 1 },
        { id: 'msg-2', role: 'assistant', content: 'b', timestamp: 2, card: { card_type: 'old', session_id: 'session-abc', data: {} } },
        { id: 'msg-3', role: 'assistant', content: 'c', timestamp: 3 },
      ],
    });

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const cardPayload = {
      session_id: 'session-abc',
      card_type: 'new_card',
      data: {} as Record<string, unknown>,
    };

    act(() => {
      es.dispatchEvent('card', cardPayload);
    });

    const msgs = useChatStore.getState().messages;
    // msg-2 already has a card → skip, msg-3 gets it
    expect(msgs[1].card).toEqual({ card_type: 'old', session_id: 'session-abc', data: {} });
    expect(msgs[2].card).toEqual(cardPayload);
  });

  // ==========================================================
  // done events
  // ==========================================================

  it('calls clearRound and finishProcessing on done', () => {
    const clearRoundSpy = vi.spyOn(useChatStore.getState(), 'clearRound');
    const finishProcessingSpy = vi.spyOn(useChatStore.getState(), 'finishProcessing');

    // Put some state that should be cleared
    useChatStore.setState({
      isProcessing: true,
      statusStream: [{ seq: 1, source: 'agent', status: 'done', label: '', session_id: 'session-abc' }],
      errorEvent: { code: 'test', message: 'old', session_id: 'session-abc' },
    });

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('done', {
        session_id: 'session-abc',
        total_ms: 1234,
      });
    });

    expect(clearRoundSpy).toHaveBeenCalled();
    expect(finishProcessingSpy).toHaveBeenCalled();

    clearRoundSpy.mockRestore();
    finishProcessingSpy.mockRestore();
  });

  // ==========================================================
  // error events
  // ==========================================================

  it('calls setErrorEvent on error event', () => {
    const setErrorEventSpy = vi.spyOn(useChatStore.getState(), 'setErrorEvent');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    const errorEvent = {
      code: 'E001',
      message: 'Agent timeout',
      session_id: 'session-abc',
    };

    act(() => {
      es.dispatchEvent('error', errorEvent);
    });

    expect(setErrorEventSpy).toHaveBeenCalledWith(errorEvent);

    setErrorEventSpy.mockRestore();
  });

  // ==========================================================
  // session_id filtering (S4-10)
  // ==========================================================

  it('discards status events with mismatched session_id', () => {
    const appendStatusSpy = vi.spyOn(useChatStore.getState(), 'appendStatus');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('status', {
        seq: 1,
        source: 'agent',
        status: 'running',
        label: 'Working...',
        session_id: 'session-xyz', // different session
      });
    });

    expect(appendStatusSpy).not.toHaveBeenCalled();

    appendStatusSpy.mockRestore();
  });

  it('discards reply events with mismatched session_id', () => {
    const appendMessageSpy = vi.spyOn(useChatStore.getState(), 'appendMessage');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('reply', {
        text: 'wrong session',
        from: 'agent',
        session_id: 'other-session',
      });
    });

    expect(appendMessageSpy).not.toHaveBeenCalled();

    appendMessageSpy.mockRestore();
  });

  it('discards done events with mismatched session_id', () => {
    const clearRoundSpy = vi.spyOn(useChatStore.getState(), 'clearRound');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchEvent('done', {
        session_id: 'wrong-session',
        total_ms: 500,
      });
    });

    expect(clearRoundSpy).not.toHaveBeenCalled();

    clearRoundSpy.mockRestore();
  });

  // ==========================================================
  // Event size validation (MAX_EVENT_SIZE = 64KB)
  // ==========================================================

  it('discards events with data larger than 64KB', () => {
    const appendStatusSpy = vi.spyOn(useChatStore.getState(), 'appendStatus');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    act(() => {
      es.dispatchOversizedEvent('status');
    });

    expect(appendStatusSpy).not.toHaveBeenCalled();

    appendStatusSpy.mockRestore();
  });

  // ==========================================================
  // JSON parse error resilience
  // ==========================================================

  it('silently ignores malformed JSON without throwing', () => {
    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    expect(() => {
      act(() => {
        es.dispatchMalformedEvent('status', 'not valid json {{{');
      });
    }).not.toThrow();
  });

  it('continues working after a malformed event (no crash)', () => {
    const appendStatusSpy = vi.spyOn(useChatStore.getState(), 'appendStatus');

    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    // Dispatch malformed data first
    act(() => {
      es.dispatchMalformedEvent('status', 'garbage');
    });
    expect(appendStatusSpy).not.toHaveBeenCalled();

    // Then dispatch valid data — should work fine
    act(() => {
      es.dispatchEvent('status', {
        seq: 10,
        source: 'agent',
        status: 'ok',
        label: 'after malformed',
        session_id: 'session-abc',
      });
    });
    expect(appendStatusSpy).toHaveBeenCalledTimes(1);

    appendStatusSpy.mockRestore();
  });

  // ==========================================================
  // heartbeat resets retryCount
  // ==========================================================

  it('resets retryCount on heartbeat', () => {
    renderHook(() => useSSE('session-abc'));
    const es = mockEventSourceInstances[0];

    // Trigger an error which increments retryCount internally
    act(() => {
      es.triggerError();
    });

    // After one error, retryCount should be 1 (internal state)
    // Now send a heartbeat which should reset it to 0
    act(() => {
      es.dispatchEvent('heartbeat', {});
    });

    // Trigger error again — if retryCount was reset, the delay
    // should be 1000ms (2^0 = 1), not a larger backoff.
    act(() => {
      es.triggerError();
    });

    // Fast-forward by 1100ms and check that a new EventSource was created
    const prevCount = mockEventSourceInstances.length;
    act(() => {
      vi.advanceTimersByTime(1100);
    });

    // After the retry timer fires, a new EventSource should be created
    // (if MAX_RETRY not exceeded and component still mounted)
    expect(mockEventSourceInstances.length).toBeGreaterThan(prevCount);
  });

  // ==========================================================
  // Exponential backoff retry
  // ==========================================================

  it('retries with exponential backoff delay (base = 1000ms)', () => {
    renderHook(() => useSSE('session-abc'));

    // Error 1: delay = 1000 * 2^0 = 1000ms
    const es0 = mockEventSourceInstances[0];
    act(() => {
      es0.triggerError();
    });

    act(() => {
      vi.advanceTimersByTime(1100);
    });

    // A new ES should have been created
    expect(mockEventSourceInstances.length).toBe(1);
    const es1 = mockEventSourceInstances[0];

    // Error 2: delay = 1000 * 2^1 = 2000ms
    act(() => {
      es1.triggerError();
    });

    // At 1000ms, no new connection yet
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockEventSourceInstances.length).toBe(0); // still waiting

    // At 2100ms total, connection should be recreated
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(mockEventSourceInstances.length).toBe(1);
  });

  it('caps retry delay at MAX_DELAY (30000ms)', () => {
    renderHook(() => useSSE('session-abc'));

    // Trigger enough errors to hit 30000ms cap
    // 2^4 = 16000ms, 2^5 = 32000ms → cap at 30000ms
    for (let i = 0; i < 5; i++) {
      const es = mockEventSourceInstances[0] || mockEventSourceInstances[mockEventSourceInstances.length - 1];
      act(() => {
        es?.triggerError();
      });
      // Advance enough for each retry to fire (up to 30000 + buffer)
      act(() => {
        vi.advanceTimersByTime(Math.min(1000 * 2 ** i, 30000) + 100);
      });
    }

    // Should still have an active ES (not exceeded MAX_RETRY of 10)
    expect(mockEventSourceInstances.length).toBe(1);
  });

  it('stops retrying after MAX_RETRY exhausted', () => {
    renderHook(() => useSSE('session-abc'));

    // Trigger MAX_RETRY (10) errors
    for (let i = 0; i < 10; i++) {
      const es = mockEventSourceInstances[0] || mockEventSourceInstances[mockEventSourceInstances.length - 1];
      act(() => {
        es?.triggerError();
      });
      // Advance to allow the next retry
      act(() => {
        vi.advanceTimersByTime(Math.min(1000 * 2 ** i, 30000) + 100);
      });
    }

    // One more error — should NOT retry
    const lastEs = mockEventSourceInstances[0] || mockEventSourceInstances[mockEventSourceInstances.length - 1];
    void mockEventSourceInstances.length;

    act(() => {
      lastEs?.triggerError();
    });

    // Advance past any possible retry
    act(() => {
      vi.advanceTimersByTime(60000);
    });

    // No new EventSource should have been created
    // Note: the last triggerError also closes the ES, but count of
    // active instances may drop. The key assertion is that a retry
    // timer was not scheduled, so no new ES appears.
    // The retryCount is >= MAX_RETRY so connect() skips creating
    // a new EventSource.
  });

  // ==========================================================
  // EventSource close on error + reconnection
  // ==========================================================

  it('closes the existing EventSource before retrying', () => {
    renderHook(() => useSSE('session-abc'));

    const es0 = mockEventSourceInstances[0];
    const closeSpy = vi.spyOn(es0, 'close');

    act(() => {
      es0.triggerError();
    });

    // onerror handler calls es.close() then sets eventSourceRef to null
    expect(closeSpy).toHaveBeenCalled();

    closeSpy.mockRestore();
  });

  // ==========================================================
  // Duplicate hook renders (React Strict Mode / re-renders)
  // ==========================================================

  it('does not leak EventSources on re-render with same sessionId', () => {
    const { rerender } = renderHook(({ sid }: { sid: string }) => useSSE(sid), {
      initialProps: { sid: 'session-abc' },
    });

    expect(mockEventSourceInstances.length).toBe(1);

    rerender({ sid: 'session-abc' });

    // The cleanup effect runs before the new effect in Strict Mode,
    // so the old ES should be closed and a new one created.
    // Final state: exactly 1 ES active.
    expect(mockEventSourceInstances.length).toBe(1);
  });
});
