import { useChatStore } from '../store/chatStore';

export function StatusBar() {
  const statusStream = useChatStore((s) => s.statusStream);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const sseConnected = useChatStore((s) => s.sseConnected);

  const sorted = [...statusStream].sort((a, b) => a.seq - b.seq);

  return (
    <div className="status-bar">
      <div className="status-indicators">
        <span className={`status-dot ${sseConnected ? 'connected' : 'disconnected'}`} />
        <span className="status-label">
          {sseConnected ? '已连接' : '未连接'}
        </span>
        {isProcessing && <span className="status-processing">处理中...</span>}
      </div>
      {sorted.length > 0 && (
        <div className="status-stream">
          {sorted.map((s) => (
            <div key={s.seq} className={`status-item status-${s.status}`}>
              <span className="status-source">{s.source}</span>
              <span className="status-text">{s.label || s.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
