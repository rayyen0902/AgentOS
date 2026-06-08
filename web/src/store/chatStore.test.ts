// @vitest-environment node

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useChatStore } from './chatStore';
import type { Message } from '../types/store';
import type { InterruptRequest } from '../types/sse';
import type { StatusEvent } from '../types/sse';

const makeMsg = (overrides: Partial<Message> = {}): Message => ({
  id: 'msg-1',
  role: 'user',
  content: 'hello',
  timestamp: 1700000000000,
  ...overrides,
});

const makeStatus = (overrides: Partial<StatusEvent> = {}): StatusEvent => ({
  seq: 1,
  source: 'orchestrator',
  status: 'started',
  label: 'Processing',
  session_id: 'sess-1',
  ...overrides,
});

const makeInterrupt = (): InterruptRequest => ({
  session_id: 'sess-1',
  interrupt_id: 'int-1',
  message: 'Choose an option',
  options: [
    { label: 'Yes', value: 'yes' },
    { label: 'No', value: 'no' },
  ],
});

beforeEach(() => {
  useChatStore.setState(useChatStore.getInitialState());
});

// ---------------------------------------------------------------------------
// appendMessage
// ---------------------------------------------------------------------------
describe('appendMessage', () => {
  it('appends message to empty array', () => {
    const msg = makeMsg({ content: 'hello' });
    const store = useChatStore.getState();

    store.appendMessage(msg);

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ role: 'user', content: 'hello' });
  });

  it('truncates content over 2000 chars', () => {
    const longContent = 'x'.repeat(2001);
    const msg = makeMsg({ content: longContent });

    useChatStore.getState().appendMessage(msg);

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content.length).toBeLessThanOrEqual(2000);
    expect(messages[0].content.length).toBe(2000);
  });

  it('does not truncate content at 2000 chars', () => {
    const exactly2000 = 'y'.repeat(2000);
    const msg = makeMsg({ content: exactly2000 });

    useChatStore.getState().appendMessage(msg);

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe(exactly2000);
  });

  it('does not truncate short content', () => {
    const msg = makeMsg({ content: 'short' });

    useChatStore.getState().appendMessage(msg);

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe('short');
  });

  it('appends multiple messages in order', () => {
    const msg1 = makeMsg({ id: '1', content: 'first' });
    const msg2 = makeMsg({ id: '2', content: 'second' });
    const store = useChatStore.getState();

    store.appendMessage(msg1);
    store.appendMessage(msg2);

    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(2);
    expect(messages[0].content).toBe('first');
    expect(messages[1].content).toBe('second');
  });
});

// ---------------------------------------------------------------------------
// appendStatus
// ---------------------------------------------------------------------------
describe('appendStatus', () => {
  it('adds new status event', () => {
    const event = makeStatus({ seq: 1, status: 'started' });

    useChatStore.getState().appendStatus(event);

    const stream = useChatStore.getState().statusStream;
    expect(stream).toHaveLength(1);
    expect(stream[0]).toMatchObject({ seq: 1, status: 'started' });
  });

  it('upserts existing status by seq', () => {
    const store = useChatStore.getState();
    store.appendStatus(makeStatus({ seq: 1, status: 'started' }));
    store.appendStatus(makeStatus({ seq: 1, status: 'completed' }));

    const stream = useChatStore.getState().statusStream;
    expect(stream).toHaveLength(1);
    expect(stream[0].status).toBe('completed');
  });

  it('adds second status with different seq', () => {
    const store = useChatStore.getState();
    store.appendStatus(makeStatus({ seq: 1 }));
    store.appendStatus(makeStatus({ seq: 2 }));

    const stream = useChatStore.getState().statusStream;
    expect(stream).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// startProcessing / finishProcessing
// ---------------------------------------------------------------------------
describe('startProcessing / finishProcessing', () => {
  it('startProcessing sets isProcessing true', () => {
    useChatStore.getState().startProcessing();
    expect(useChatStore.getState().isProcessing).toBe(true);
  });

  it('startProcessing clears errorEvent', () => {
    useChatStore.setState({ errorEvent: { code: 500, message: 'err', session_id: 's1' } });

    useChatStore.getState().startProcessing();

    expect(useChatStore.getState().errorEvent).toBeNull();
  });

  it('finishProcessing sets isProcessing false', () => {
    const store = useChatStore.getState();
    store.startProcessing();
    store.finishProcessing();

    expect(useChatStore.getState().isProcessing).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// clearRound
// ---------------------------------------------------------------------------
describe('clearRound', () => {
  it('resets statusStream to empty', () => {
    const store = useChatStore.getState();
    store.appendStatus(makeStatus({ seq: 1 }));
    store.appendStatus(makeStatus({ seq: 2 }));

    store.clearRound();

    expect(useChatStore.getState().statusStream).toEqual([]);
  });

  it('resets currentCard to null', () => {
    useChatStore.setState({ currentCard: { session_id: 's1', card_type: 'product', data: {} } });

    useChatStore.getState().clearRound();

    expect(useChatStore.getState().currentCard).toBeNull();
  });

  it('resets errorEvent to null', () => {
    useChatStore.setState({ errorEvent: { code: 500, message: 'err', session_id: 's1' } });

    useChatStore.getState().clearRound();

    expect(useChatStore.getState().errorEvent).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// replyInterrupt
// ---------------------------------------------------------------------------
describe('replyInterrupt', () => {
  const localStorageMock = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    key: vi.fn(),
    length: 0,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('localStorage', localStorageMock);
    vi.stubGlobal('import', { meta: { env: { VITE_API_BASE_URL: '' } } });
    localStorageMock.getItem.mockReset();
  });

  it('does nothing when no interrupt', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    // Ensure interrupt is null (default from getInitialState)

    await useChatStore.getState().replyInterrupt('yes');

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('POSTs to interrupt endpoint on reply', async () => {
    const fakeResponse = { ok: true, json: () => Promise.resolve({}) } as Response;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(fakeResponse);
    const interrupt = makeInterrupt();

    useChatStore.setState({ interrupt });

    await useChatStore.getState().replyInterrupt('opt1');

    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/v1/chat/interrupt');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(
      JSON.stringify({
        session_id: interrupt.session_id,
        interrupt_id: interrupt.interrupt_id,
        choice: 'opt1',
      }),
    );
  });

  it('clears interrupt on success', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    useChatStore.setState({ interrupt: makeInterrupt() });

    await useChatStore.getState().replyInterrupt('yes');

    expect(useChatStore.getState().interrupt).toBeNull();
  });

  it('sets isProcessing on success', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    useChatStore.setState({ interrupt: makeInterrupt() });

    await useChatStore.getState().replyInterrupt('yes');

    expect(useChatStore.getState().isProcessing).toBe(true);
  });

  it('leaves interrupt on failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({}),
    } as Response);

    const interrupt = makeInterrupt();
    useChatStore.setState({ interrupt });

    await useChatStore.getState().replyInterrupt('yes');

    expect(useChatStore.getState().interrupt).toEqual(interrupt);
  });

  it('reads JWT from localStorage', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
    localStorageMock.getItem.mockReturnValue('test-jwt-token');

    useChatStore.setState({ interrupt: makeInterrupt() });

    await useChatStore.getState().replyInterrupt('yes');

    expect(localStorageMock.getItem).toHaveBeenCalledWith('jwt');

    const [_, init] = fetchSpy.mock.calls[0];
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: 'Bearer test-jwt-token',
    });
  });
});
