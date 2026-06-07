import { StatusEvent, InterruptRequest, CardPayload, ErrorEvent } from './sse';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  card?: CardPayload | null;
  timestamp: number;
}

export interface ChatStore {
  messages: Message[];
  statusStream: StatusEvent[];
  interrupt: InterruptRequest | null;
  currentCard: CardPayload | null;
  errorEvent: ErrorEvent | null;
  isProcessing: boolean;
  sseConnected: boolean;

  appendMessage: (msg: Message) => void;
  appendStatus: (event: StatusEvent) => void;
  setInterrupt: (req: InterruptRequest | null) => void;
  setCard: (card: CardPayload | null) => void;
  setErrorEvent: (err: ErrorEvent | null) => void;
  finishProcessing: () => void;
  replyInterrupt: (option: string) => Promise<void>;
}
