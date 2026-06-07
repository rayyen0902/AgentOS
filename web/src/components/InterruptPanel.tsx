import { useChatStore } from '../store/chatStore';

export function InterruptPanel() {
  const interrupt = useChatStore((s) => s.interrupt);
  const replyInterrupt = useChatStore((s) => s.replyInterrupt);

  if (!interrupt) return null;

  return (
    <div className="interrupt-panel">
      <p className="interrupt-message">{interrupt.message}</p>
      <div className="interrupt-options">
        {interrupt.options.map((opt) => (
          <button
            key={opt.value}
            className="interrupt-btn"
            onClick={() => replyInterrupt(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
