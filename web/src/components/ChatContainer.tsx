import { useSSE } from '../hooks/useSSE';
import { useChatStore } from '../store/chatStore';
import { MessageList } from './MessageList';
import { StatusBar } from './StatusBar';
import { InterruptPanel } from './InterruptPanel';
import { ChatInput } from './ChatInput';
import { useEffect } from 'react';

const DEMO_SESSION_ID = 'demo-session';

export function ChatContainer() {
  const sseConnected = useChatStore((s) => s.sseConnected);

  useSSE(DEMO_SESSION_ID);

  useEffect(() => {
    useChatStore.setState({ sseConnected: true });
  }, []);

  return (
    <div className="chat-container">
      <header className="chat-header">
        <h2>AgentOS</h2>
        <span className={`connection-badge ${sseConnected ? 'online' : 'offline'}`}>
          {sseConnected ? 'SSE 已连接' : 'SSE 断开'}
        </span>
      </header>
      <StatusBar />
      <MessageList />
      <InterruptPanel />
      <ChatInput />
    </div>
  );
}
