import { useEffect, useState, useRef } from 'react';
import { DashboardMetric } from '../types/admin';
import { adminFetch } from './api';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

const POLL_INTERVAL = 30_000;

export function AdminDashboard() {
  const [metrics, setMetrics] = useState<DashboardMetric | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    mountedRef.current = true;

    const fetchMetrics = async () => {
      // Don't show full-page loading on refresh
      if (!metrics) setLoading(true);
      try {
        const res = await adminFetch('/api/v1/admin/dashboard/metrics');
        const data = await res.json();
        if (!mountedRef.current) return;
        if (data.code === 0) {
          setMetrics(data.data);
          setError(null);
        } else {
          setError(data.message || '加载失败');
        }
      } catch {
        if (!mountedRef.current) return;
        // Silent on poll; show error only on first load
        if (!metrics) setError('网络错误');
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    };

    fetchMetrics(); // first load

    pollRef.current = setInterval(fetchMetrics, POLL_INTERVAL);

    return () => {
      mountedRef.current = false;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;

  const current = metrics || {
    accuracy: 0,
    conversion: 0,
    retention: 0,
    trust: 0,
    history: [],
  };

  const metricsList = [
    { key: 'accuracy', label: 'Accuracy 准确度', desc: '推荐产品是否匹配肤质' },
    { key: 'conversion', label: 'Conversion 转化率', desc: '推荐→选购/下单转化' },
    { key: 'retention', label: 'Retention 留存率', desc: '用户 7 日内回访率' },
    { key: 'trust', label: 'Trust 信任度', desc: '采纳率 / 追问率' },
  ] as const;

  return (
    <div className="admin-dashboard">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Agent 评价看板</h2>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          每 30s 自动刷新
        </span>
      </div>
      {error && (
        <div className="admin-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="metrics-grid">
        {metricsList.map(({ key, label, desc }) => (
          <div key={key} className="metric-card">
            <h4>{label}</h4>
            <div className="metric-value">
              {(current[key] * 100).toFixed(1)}%
            </div>
            <p className="metric-desc">{desc}</p>
          </div>
        ))}
      </div>

      {current.history.length > 0 && (
        <div className="trend-chart">
          <h3>趋势图</h3>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={current.history}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="date" stroke="#999" fontSize={12} />
              <YAxis domain={[0, 1]} stroke="#999" fontSize={12} />
              <Tooltip
                contentStyle={{ background: '#16213e', border: '1px solid #333' }}
                formatter={(value: any) => `${(Number(value) * 100).toFixed(1)}%`}
              />
              <Legend />
              <Line type="monotone" dataKey="accuracy" stroke="#e94560" name="Accuracy" dot={false} />
              <Line type="monotone" dataKey="conversion" stroke="#4caf50" name="Conversion" dot={false} />
              <Line type="monotone" dataKey="retention" stroke="#2196f3" name="Retention" dot={false} />
              <Line type="monotone" dataKey="trust" stroke="#ff9800" name="Trust" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
