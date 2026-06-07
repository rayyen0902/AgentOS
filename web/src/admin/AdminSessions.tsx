import { useState, useEffect, FormEvent } from 'react';
import { AdminSessionFilter } from '../types/admin';

interface SessionLog {
  session_id: string;
  tenant_id: number;
  tenant_name: string;
  platform: string;
  message_count: number;
  started_at: string;
  ended_at: string | null;
}

export function AdminSessions() {
  const [sessions, setSessions] = useState<SessionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<AdminSessionFilter>({});

  const fetchSessions = async (f?: AdminSessionFilter) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (f?.tenant_id) params.set('tenant_id', String(f.tenant_id));
      if (f?.start_time) params.set('start_time', f.start_time);
      if (f?.end_time) params.set('end_time', f.end_time);

      const res = await fetch(`/api/v1/admin/sessions?${params.toString()}`);
      const data = await res.json();
      if (data.code === 0) {
        setSessions(data.data || []);
      } else {
        setError(data.message || '加载失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleFilter = (e: FormEvent) => {
    e.preventDefault();
    fetchSessions(filter);
  };

  return (
    <div className="admin-sessions">
      <h2>会话日志</h2>
      {error && (
        <div className="admin-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <form className="session-filter" onSubmit={handleFilter}>
        <label>
          租户ID
          <input
            type="number"
            value={filter.tenant_id || ''}
            onChange={(e) =>
              setFilter((f) => ({
                ...f,
                tenant_id: e.target.value ? Number(e.target.value) : undefined,
              }))
            }
            placeholder="按租户ID筛选"
          />
        </label>
        <label>
          开始时间
          <input
            type="datetime-local"
            value={filter.start_time || ''}
            onChange={(e) =>
              setFilter((f) => ({ ...f, start_time: e.target.value || undefined }))
            }
          />
        </label>
        <label>
          结束时间
          <input
            type="datetime-local"
            value={filter.end_time || ''}
            onChange={(e) =>
              setFilter((f) => ({ ...f, end_time: e.target.value || undefined }))
            }
          />
        </label>
        <button type="submit" className="btn-filter">
          筛选
        </button>
        <button
          type="button"
          className="btn-reset"
          onClick={() => {
            setFilter({});
            fetchSessions();
          }}
        >
          重置
        </button>
      </form>

      {loading ? (
        <div className="admin-loading">加载中...</div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>会话ID</th>
              <th>租户</th>
              <th>平台</th>
              <th>消息数</th>
              <th>开始时间</th>
              <th>结束时间</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.session_id}>
                <td className="mono-cell">{s.session_id}</td>
                <td>{s.tenant_name} (#{s.tenant_id})</td>
                <td>{s.platform}</td>
                <td>{s.message_count}</td>
                <td>{new Date(s.started_at).toLocaleString('zh-CN')}</td>
                <td>{s.ended_at ? new Date(s.ended_at).toLocaleString('zh-CN') : '-'}</td>
              </tr>
            ))}
            {sessions.length === 0 && (
              <tr>
                <td colSpan={6} className="empty-cell">
                  暂无数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
