import { useState, useEffect } from 'react';

interface PlatformConfig {
  id: number;
  platform: string;
  name: string;
  app_id: string;
  enabled: boolean;
  updated_at: string;
}

// Platform names are referenced from the API response directly

export function AdminPlatforms() {
  const [configs, setConfigs] = useState<PlatformConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ app_id: '', enabled: true });

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/admin/platforms');
      const data = await res.json();
      if (data.code === 0) {
        setConfigs(data.data || []);
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
    fetchConfigs();
  }, []);

  const startEdit = (cfg: PlatformConfig) => {
    setEditingId(cfg.id);
    setEditForm({ app_id: cfg.app_id, enabled: cfg.enabled });
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const saveEdit = async (id: number) => {
    try {
      const res = await fetch(`/api/v1/admin/platforms/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });
      const data = await res.json();
      if (data.code === 0) {
        setConfigs((prev) =>
          prev.map((c) =>
            c.id === id
              ? { ...c, app_id: editForm.app_id, enabled: editForm.enabled }
              : c
          )
        );
        setEditingId(null);
      } else {
        setError(data.message || '保存失败');
      }
    } catch {
      setError('网络错误');
    }
  };

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="admin-platforms">
      <h2>平台配置</h2>
      {error && (
        <div className="admin-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <table className="admin-table">
        <thead>
          <tr>
            <th>平台</th>
            <th>名称</th>
            <th>App ID</th>
            <th>状态</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {configs.map((cfg) => (
            <tr key={cfg.id}>
              <td>{cfg.platform}</td>
              <td>{cfg.name}</td>
              <td>
                {editingId === cfg.id ? (
                  <input
                    type="text"
                    value={editForm.app_id}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, app_id: e.target.value }))
                    }
                  />
                ) : (
                  <span className="mono-cell">{cfg.app_id || '-'}</span>
                )}
              </td>
              <td>
                {editingId === cfg.id ? (
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={editForm.enabled}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, enabled: e.target.checked }))
                      }
                    />
                    {editForm.enabled ? '启用' : '禁用'}
                  </label>
                ) : (
                  <span className={`status-tag ${cfg.enabled ? 'status-active' : 'status-suspended'}`}>
                    {cfg.enabled ? '启用' : '禁用'}
                  </span>
                )}
              </td>
              <td>{new Date(cfg.updated_at).toLocaleString('zh-CN')}</td>
              <td>
                {editingId === cfg.id ? (
                  <>
                    <button className="btn-approve" onClick={() => saveEdit(cfg.id)}>
                      保存
                    </button>
                    <button className="btn-reject" onClick={cancelEdit}>
                      取消
                    </button>
                  </>
                ) : (
                  <button className="btn-edit" onClick={() => startEdit(cfg)}>
                    编辑
                  </button>
                )}
              </td>
            </tr>
          ))}
          {configs.length === 0 && (
            <tr>
              <td colSpan={6} className="empty-cell">
                暂无配置数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
