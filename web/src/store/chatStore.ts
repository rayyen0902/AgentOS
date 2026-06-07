import { create } from 'zustand';
import { ChatStore } from '../types/store';

const MAX_MESSAGE_LENGTH = 2000;

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  statusStream: [],
  interrupt: null,
  currentCard: null,
  errorEvent: null,
  isProcessing: false,
  sseConnected: false,

  appendMessage: (msg) => {
    const trimmed = {
      ...msg,
      content: msg.content.length > MAX_MESSAGE_LENGTH
        ? msg.content.slice(0, MAX_MESSAGE_LENGTH)
        : msg.content,
    };
    set((state) => ({
      messages: [...state.messages, trimmed],
    }));
  },

  appendStatus: (event) => {
    set((state) => {
      const idx = state.statusStream.findIndex((s) => s.seq === event.seq);
      if (idx >= 0) {
        const updated = [...state.statusStream];
        updated[idx] = event;
        return { statusStream: updated };
      }
      return { statusStream: [...state.statusStream, event] };
    });
  },

  setInterrupt: (req) => {
    set({ interrupt: req });
  },

  setCard: (card) => {
    set({ currentCard: card });
  },

  setErrorEvent: (err) => {
    set({ errorEvent: err });
  },

  finishProcessing: () => {
    set({ isProcessing: false });
  },

  replyInterrupt: async (option) => {
    const { interrupt } = get();
    if (!interrupt) return;

    const res = await fetch('/api/v1/chat/interrupt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: interrupt.session_id,
        interrupt_id: interrupt.interrupt_id,
        choice: option,
      }),
    });

    if (res.ok) {
      set({ interrupt: null, isProcessing: true });
    }
  },
}));
