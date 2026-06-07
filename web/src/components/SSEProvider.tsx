import { createContext, useContext, useState } from 'react';
import { useSSE } from '../hooks/useSSE';

interface SSEContextValue {
  sessionId: string;
  setSessionId: (id: string) => void;
}

const SSEContext = createContext<SSEContextValue | null>(null);

export function useSSEContext() {
  const ctx = useContext(SSEContext);
  if (!ctx) throw new Error('useSSEContext must be used within SSEProvider');
  return ctx;
}

export function SSEProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState('demo-session');

  useSSE(sessionId);

  const value: SSEContextValue = { sessionId, setSessionId };

  return <SSEContext.Provider value={value}>{children}</SSEContext.Provider>;
}
