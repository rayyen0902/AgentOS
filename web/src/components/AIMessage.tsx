import { Message } from '../types/store';
import { SafeCardRenderer } from '../cards/SafeCardRenderer';

interface AIMessageProps {
  message: Message;
  onInterruptReply?: (option: string) => void;
}

export function AIMessage({ message, onInterruptReply }: AIMessageProps) {
  return (
    <div className="message ai-message">
      <div className="message-bubble ai-bubble">
        {message.content && <p className="message-text">{message.content}</p>}
        {message.card && (
          <SafeCardRenderer
            card={message.card}
            onInterruptReply={onInterruptReply}
          />
        )}
      </div>
      <span className="message-time">
        {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  );
}
