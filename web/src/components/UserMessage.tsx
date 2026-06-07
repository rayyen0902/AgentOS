import { Message } from '../types/store';

interface UserMessageProps {
  message: Message;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="message user-message">
      <div className="message-bubble user-bubble">
        <p className="message-text">{message.content}</p>
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
