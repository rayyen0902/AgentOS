import { useChatStore } from '../store/chatStore';
import { UserMessage } from './UserMessage';
import { AIMessage } from './AIMessage';
import { useEffect, useRef } from 'react';

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const replyInterrupt = useChatStore((s) => s.replyInterrupt);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="message-list-empty">
        <p>发送消息开始对话</p>
      </div>
    );
  }

  return (
    <div className="message-list" aria-live="polite">
      {messages.map((msg) =>
        msg.role === 'user' ? (
          <UserMessage key={msg.id} message={msg} />
        ) : (
          <AIMessage
            key={msg.id}
            message={msg}
            onInterruptReply={replyInterrupt}
          />
        )
      )}
      <div ref={bottomRef} />
    </div>
  );
}
