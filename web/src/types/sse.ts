export interface StatusEvent {
  seq: number;
  source: string;
  status: string;
  label: string;
  session_id: string;
  duration_ms?: number;
  created_at?: string;
}

export interface ReplyEvent {
  text: string;
  from: string;
  session_id: string;
}

export interface InterruptRequest {
  session_id: string;
  interrupt_id: string;
  message: string;
  options: InterruptOption[];
}

export interface InterruptOption {
  label: string;
  value: string;
}

export interface CardPayload {
  session_id: string;
  card_type: string;
  data: Record<string, unknown>;
}

export interface DoneEvent {
  session_id: string;
  total_ms: number;
}

export interface ErrorEvent {
  code: string | number;
  message: string;
  session_id: string;
}

export type SSECallbackMap = {
  status: (event: StatusEvent) => void;
  reply: (event: ReplyEvent) => void;
  interrupt: (event: InterruptRequest) => void;
  card: (event: CardPayload) => void;
  done: (event: DoneEvent) => void;
  error: (event: ErrorEvent) => void;
  heartbeat: () => void;
};
