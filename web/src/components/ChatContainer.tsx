import { useSSE } from '../hooks/useSSE';
import { useChatStore } from '../store/chatStore';
import { MessageList } from './MessageList';
import { StatusBar } from './StatusBar';
import { InterruptPanel } from './InterruptPanel';
import { ChatInput } from './ChatInput';
import { useState, useEffect } from 'react';

interface Props {
  widgetMode?: boolean;
  tenantId?: string;
}

export function ChatContainer({ widgetMode = false, tenantId: _tenantId }: Props) {
  const sseConnected = useChatStore((s) => s.sseConnected);
  const [sessionId] = useState(() => {
    const tid = _tenantId;
    if (tid) return `widget-${tid}`;
    return localStorage.getItem('session_id') || 'demo-session';
  });

  useSSE(sessionId);

  useEffect(() => {
    if (_tenantId) {
      localStorage.setItem('session_id', sessionId);
    }
  }, [_tenantId, sessionId]);

  // widgetMode 渲染简化版，Step 9 实现
  void widgetMode;
  void widgetMode;

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
