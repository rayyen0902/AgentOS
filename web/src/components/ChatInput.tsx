import { useState, FormEvent, useRef } from 'react';
import { useChatStore } from '../store/chatStore';
import { Message } from '../types/store';

const MAX_MESSAGE_LENGTH = 2000;
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export function ChatInput() {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const startProcessing = useChatStore((s) => s.startProcessing);

  // S4-12 / S4-18: validate正确分离截断和校验，截断时提示用户且阻止提交
  const validate = (content: string): { valid: boolean; content: string; truncated: boolean } => {
    if (content.length > MAX_MESSAGE_LENGTH) {
      return { valid: false, content: content.slice(0, MAX_MESSAGE_LENGTH), truncated: true };
    }
    return { valid: true, content, truncated: false };
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || isProcessing) return;

    const { valid, content, truncated } = validate(trimmed);
    if (truncated) {
      setText(content);
      setError(`消息过长，已截断至${MAX_MESSAGE_LENGTH}字`);
      return;
    }
    if (!valid) {
      setError('消息无效');
      return;
    }
    setError(null);

    const userMsg: Message = {
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    };

    // S4-04: startProcessing 防止并发多发
    startProcessing();
    appendMessage(userMsg);
    setText('');

    const token = localStorage.getItem('jwt');
    const body = {
      session_id: localStorage.getItem('session_id') || 'demo-session',
      type: 'text',
      content,
      image_url: null,
      interrupt_reply: false,
    };
    try {
      const res = await fetch(`${API_BASE}/api/v1/chat/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setError((errData as { message?: string }).message || '发送失败，请重试');
      }
    } catch {
      setError('网络错误，请检查连接');
    }
  };

  // S4-13: 图片上传接入消息体
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_IMAGE_SIZE) {
      setError('图片过大，请重新上传（上限10MB）');
      return;
    }

    setError(null);

    // 图片消息直接发送
    const userMsg: Message = {
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      role: 'user',
      content: `[图片: ${file.name}]`,
      timestamp: Date.now(),
    };

    startProcessing();
    appendMessage(userMsg);

    const formData = new FormData();
    formData.append('image', file);
    formData.append('session_id', localStorage.getItem('session_id') || 'demo-session');
    formData.append('type', 'image');

    const token = localStorage.getItem('jwt');
    fetch('/api/v1/chat/message', {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    }).then((res) => {
      if (!res.ok) setError('图片发送失败');
    }).catch(() => {
      setError('网络错误，请检查连接');
    });
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
