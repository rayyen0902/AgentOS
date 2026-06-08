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
    // S4-18: 截断时标记，ChatInput 层提示用户
    const truncated = msg.content.length > MAX_MESSAGE_LENGTH;
    const trimmed = {
      ...msg,
      content: truncated ? msg.content.slice(0, MAX_MESSAGE_LENGTH) : msg.content,
    };
    set((state) => ({
      messages: [...state.messages, trimmed],
    }));
    return trimmed;
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

  startProcessing: () => {
    set({ isProcessing: true, errorEvent: null });
  },

  finishProcessing: () => {
    set({ isProcessing: false });
  },

  clearRound: () => {
    set({ statusStream: [], currentCard: null, errorEvent: null });
  },

  replyInterrupt: async (option) => {
    const { interrupt } = get();
    if (!interrupt) return;

    // S4-19: replyInterrupt 也带 auth header
    const token = localStorage.getItem('jwt');
    const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/v1/chat/interrupt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
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
