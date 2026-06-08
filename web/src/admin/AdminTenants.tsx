import { useState, useEffect, useCallback } from 'react';
import { TenantInfo, ApprovalResponse } from '../types/admin';
import { adminFetch } from './api';

export function AdminTenants() {
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTenant, setSelectedTenant] = useState<TenantInfo | null>(null);
  const [approvalResult, setApprovalResult] = useState<ApprovalResponse['data'] | null>(null);

  const fetchTenants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminFetch('/api/v1/admin/tenants');
      const data = await res.json();
      if (data.code === 0) {
        setTenants(data.data || []);
      } else {
        setError(data.message || '加载失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTenants();
  }, [fetchTenants]);

  const handleApprove = async (id: number) => {
    try {
      const res = await adminFetch(`/api/v1/admin/tenants/${id}/approve`, {
        method: 'PUT',
      });
      const data: ApprovalResponse = await res.json();
      if (data.code === 0) {
        setTenants((prev) =>
          prev.map((t) => (t.id === id ? { ...t, status: 'active' } : t))
        );
        if (data.data) {
          setApprovalResult(data.data);
        }
      } else {
        setError(data.message || '审批失败');
      }
    } catch {
      setError('网络错误');
    }
  };

  const handleReject = async (id: number) => {
    try {
      const res = await adminFetch(`/api/v1/admin/tenants/${id}/reject`, {
        method: 'PUT',
      });
      const data = await res.json();
      if (data.code === 0) {
        setTenants((prev) =>
          prev.map((t) => (t.id === id ? { ...t, status: 'rejected' } : t))
        );
      } else {
        setError(data.message || '操作失败');
      }
    } catch {
      setError('网络错误');
    }
  };

  const statusLabel = (s: string) => {
    const map: Record<string, string> = {
      pending: '待审批',
      active: '已通过',
      suspended: '已停用',
      rejected: '已拒绝',
    };
    return map[s] || s;
  };

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="admin-tenants">
      <h2>租户管理</h2>
      {error && (
        <div className="admin-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <table className="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>品牌名</th>
            <th>联系人</th>
            <th>手机号</th>
            <th>邮箱</th>
            <th>状态</th>
            <th>注册时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {tenants.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>
                <button
                  className="link-btn"
                  onClick={() => setSelectedTenant(t)}
                >
                  {t.brand_name}
                </button>
              </td>
              <td>{t.contact_name}</td>
              <td>{t.phone}</td>
              <td>{t.email}</td>
              <td>
                <span className={`status-tag status-${t.status}`}>
                  {statusLabel(t.status)}
                </span>
              </td>
              <td>{new Date(t.created_at).toLocaleString('zh-CN')}</td>
              <td className="action-cell">
                {t.status === 'pending' && (
                  <>
                    <button
                      className="btn-approve"
                      onClick={() => handleApprove(t.id)}
                    >
                      通过
                    </button>
                    <button
                      className="btn-reject"
                      onClick={() => handleReject(t.id)}
                    >
                      拒绝
                    </button>
                  </>
                )}
                {t.status === 'active' && (
                  <span className="approved-text">已通过</span>
                )}
                {t.status === 'rejected' && (
                  <span className="rejected-text">已拒绝</span>
                )}
              </td>
            </tr>
          ))}
          {tenants.length === 0 && (
            <tr>
              <td colSpan={8} className="empty-cell">
                暂无数据
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* API Key modal — shown once after approval */}
      {approvalResult && (
        <div className="modal-overlay" onClick={() => setApprovalResult(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>审批通过 — 凭证信息（仅此一次）</h3>
            <dl className="detail-list">
              <dt>租户ID</dt><dd>{approvalResult.tenant_id}</dd>
              <dt>状态</dt><dd>{approvalResult.status}</dd>
              <dt>API Key</dt>
              <dd className="mono-cell">
                <code>{approvalResult.api_key}</code>
              </dd>
            </dl>
            {approvalResult.widget_snippet && (
              <div className="widget-snippet-display">
                <label>嵌入代码</label>
                <pre className="snippet-text">{approvalResult.widget_snippet}</pre>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button
                className="btn-approve"
                onClick={() => {
                  navigator.clipboard.writeText(approvalResult.api_key || '').then(
                    () => alert('API Key 已复制'),
                    () => alert('复制失败')
                  );
                }}
              >
                复制 API Key
              </button>
              <button
                className="modal-close-btn"
                onClick={() => setApprovalResult(null)}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tenant detail modal */}
      {selectedTenant && !approvalResult && (
        <div className="modal-overlay" onClick={() => setSelectedTenant(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>租户详情</h3>
            <dl className="detail-list">
              <dt>ID</dt><dd>{selectedTenant.id}</dd>
              <dt>品牌名</dt><dd>{selectedTenant.brand_name}</dd>
              <dt>联系人</dt><dd>{selectedTenant.contact_name}</dd>
              <dt>手机号</dt><dd>{selectedTenant.phone}</dd>
              <dt>邮箱</dt><dd>{selectedTenant.email}</dd>
              <dt>状态</dt><dd>{statusLabel(selectedTenant.status)}</dd>
              <dt>注册时间</dt><dd>{new Date(selectedTenant.created_at).toLocaleString('zh-CN')}</dd>
              {selectedTenant.approved_at && (
                <>
                  <dt>审批时间</dt><dd>{new Date(selectedTenant.approved_at).toLocaleString('zh-CN')}</dd>
                </>
              )}
            </dl>
            <button
              className="modal-close-btn"
              onClick={() => setSelectedTenant(null)}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
