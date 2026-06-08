import { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApprovalResponse } from '../types/admin';

const POLL_INTERVAL = 30000;

export function ApprovalPage() {
  const [searchParams] = useSearchParams();
  const tenantId = searchParams.get('tenant_id');
  const [status, setStatus] = useState<'pending' | 'active' | 'rejected' | null>(null);
  const [apiKeyData, setApiKeyData] = useState<ApprovalResponse['data'] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!tenantId) return;

    const checkStatus = async () => {
      try {
        const res = await fetch(`/api/v1/tenants/${tenantId}/status`);
        const data: ApprovalResponse = await res.json();
        if (data.code === 0 && data.data) {
          setStatus(data.data.status);
          if (data.data.status === 'active') {
            setApiKeyData(data.data);
            if (pollTimer.current) {
              clearInterval(pollTimer.current);
              pollTimer.current = null;
            }
          }
        } else {
          setError(data.message || '查询失败');
        }
      } catch {
        // network error, retry on next poll
      }
    };

    checkStatus(); // immediate first check
    pollTimer.current = setInterval(checkStatus, POLL_INTERVAL);

    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [tenantId]);

  if (!tenantId) {
    return (
      <div className="approval-page">
        <h2>缺少参数</h2>
        <p>请从注册成功页面跳转访问。</p>
      </div>
    );
  }

  if (status === 'active' && apiKeyData) {
    return (
      <div className="approval-page">
        <h2>审批已通过！</h2>
        <p>您的租户已激活，以下为您的凭证（仅显示一次，请妥善保存）：</p>

        <div className="api-key-display">
          <label>API Key</label>
          <div className="api-key-row">
            <code className="api-key-text">{apiKeyData.api_key}</code>
            <button
              className="copy-btn"
              onClick={() => {
                navigator.clipboard.writeText(apiKeyData.api_key || '').then(
                  () => alert('已复制到剪贴板'),
                  () => alert('复制失败，请手动复制')
                );
              }}
            >
              复制
            </button>
          </div>
        </div>

        {apiKeyData.widget_snippet && (
          <div className="widget-snippet-display">
            <label>嵌入代码</label>
            <pre className="snippet-text">{apiKeyData.widget_snippet}</pre>
            <button
              className="copy-btn"
              onClick={() => {
                navigator.clipboard.writeText(apiKeyData.widget_snippet || '').then(
                  () => alert('已复制到剪贴板'),
                  () => alert('复制失败，请手动复制')
                );
              }}
            >
              复制
            </button>
          </div>
        )}
      </div>
    );
  }

  if (status === 'rejected') {
    return (
      <div className="approval-page">
        <h2>审批未通过</h2>
        <p>您的注册申请未被批准，如有疑问请联系管理员。</p>
      </div>
    );
  }

  return (
    <div className="approval-page">
      <h2>注册成功</h2>
      <p>您的注册申请已提交，请等待管理员审批。</p>
      <p className="approval-hint">
        审批通过后，您将收到短信/邮件通知，届时可获取 API Key 和嵌入代码。
      </p>
      <p className="approval-hint">正在自动检测审批状态...</p>
      {error && <p className="register-error">{error}</p>}
    </div>
  );
}
