import { useState, FormEvent, useRef } from 'react';
import { useChatStore } from '../store/chatStore';
import { Message } from '../types/store';

const MAX_MESSAGE_LENGTH = 2000;
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;

export function ChatInput() {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const appendMessage = useChatStore((s) => s.appendMessage);

  const validate = (): boolean => {
    if (text.length > MAX_MESSAGE_LENGTH) {
      setError(`消息过长，已截断至${MAX_MESSAGE_LENGTH}字`);
      setText(text.slice(0, MAX_MESSAGE_LENGTH));
      return true;
    }
    setError(null);
    return true;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || isProcessing) return;
    if (!validate()) return;

    const userMsg: Message = {
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      role: 'user',
      content: trimmed,
      timestamp: Date.now(),
    };

    appendMessage(userMsg);
    setText('');

    try {
      const res = await fetch('/api/v1/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setError((errData as { message?: string }).message || '发送失败，请重试');
      }
    } catch {
      setError('网络错误，请检查连接');
    }
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_IMAGE_SIZE) {
      setError('图片过大，请重新上传（上限10MB）');
      return;
    }

    setError(null);
  };

  return (
    <div className="chat-input-wrapper">
      {error && (
        <div className="input-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>x</button>
        </div>
      )}
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="file"
          ref={fileInputRef}
          accept="image/*"
          style={{ display: 'none' }}
          onChange={handleImageUpload}
        />
        <button
          type="button"
          className="attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="上传图片"
        >
          +
        </button>
        <input
          className="text-input"
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="输入消息..."
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={isProcessing}
        />
        <button
          type="submit"
          className="send-btn"
          disabled={!text.trim() || isProcessing}
        >
          发送
        </button>
      </form>
    </div>
  );
}
