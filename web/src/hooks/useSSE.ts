import { useEffect, useRef, useCallback } from 'react';
import { useChatStore } from '../store/chatStore';
import { StatusEvent, ReplyEvent, InterruptRequest, CardPayload, DoneEvent, ErrorEvent } from '../types/sse';
import { Message } from '../types/store';

const MAX_RETRY = 10;
const MAX_DELAY = 30000;
const MAX_EVENT_SIZE = 64 * 1024;

export function useSSE(sessionId: string) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const appendMessage = useChatStore((s) => s.appendMessage);
  const appendStatus = useChatStore((s) => s.appendStatus);
  const setInterrupt = useChatStore((s) => s.setInterrupt);
  const setCard = useChatStore((s) => s.setCard);
  const setErrorEvent = useChatStore((s) => s.setErrorEvent);
  const finishProcessing = useChatStore((s) => s.finishProcessing);

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const es = new EventSource(`/api/v1/chat/stream?session_id=${encodeURIComponent(sessionId)}`);
    eventSourceRef.current = es;

    es.addEventListener('heartbeat', () => {
      retryCountRef.current = 0;
    });

    es.addEventListener('status', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: StatusEvent = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        appendStatus(data);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('reply', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: ReplyEvent = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        const msg: Message = {
          id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
          role: 'assistant',
          content: data.text,
          timestamp: Date.now(),
        };
        appendMessage(msg);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('interrupt', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: InterruptRequest = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        setInterrupt(data);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('card', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: CardPayload = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        setCard(data);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('done', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: DoneEvent = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        finishProcessing();
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('error', (e: MessageEvent) => {
      if (e.data.length > MAX_EVENT_SIZE) return;
      try {
        const data: ErrorEvent = JSON.parse(e.data);
        data.session_id = data.session_id || sessionId;
        setErrorEvent(data);
      } catch { /* ignore parse errors */ }
    });

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      if (!mountedRef.current) return;

      if (retryCountRef.current < MAX_RETRY) {
        const delay = Math.min(1000 * 2 ** retryCountRef.current, MAX_DELAY);
        timerRef.current = setTimeout(() => {
          retryCountRef.current++;
          connect();
        }, delay);
      }
    };
  }, [sessionId, appendMessage, appendStatus, setInterrupt, setCard, setErrorEvent, finishProcessing]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);
}
