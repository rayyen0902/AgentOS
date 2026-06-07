import { SkinReportCardData } from '../types/cards';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts';

interface Props {
  data: SkinReportCardData;
}

const DIMENSION_LABELS: Record<string, string> = {
  oil_level: '油性',
  sensitivity: '敏感',
  hydration: '水润',
  pigmentation: '色素',
};

export function SkinReportCard({ data }: Props) {
  const chartData = Object.entries(data.dimensions).map(([key, value]) => ({
    dimension: DIMENSION_LABELS[key] || key,
    value,
    fullMark: 5,
  }));

  return (
    <div className="card skin-report-card">
      <div className="card-header">
        <span className="card-type-badge">肤质报告</span>
      </div>

      <div className="skin-type-display">
        <h3 className="skin-type-label">{data.skin_type}</h3>
      </div>

      <div className="skin-chart-container">
        <ResponsiveContainer width="100%" height={280}>
          <RadarChart data={chartData}>
            <PolarGrid stroke="#444" />
            <PolarAngleAxis
              dataKey="dimension"
              tick={{ fill: '#ccc', fontSize: 13 }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 5]}
              tick={{ fill: '#888', fontSize: 11 }}
            />
            <Radar
              name="肤质"
              dataKey="value"
              stroke="#e94560"
              fill="#e94560"
              fillOpacity={0.25}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <div className="skin-detail-row">
        {data.concerns.length > 0 && (
          <div className="skin-concerns">
            <h5>🔍 肌肤问题</h5>
            <ul>
              {data.concerns.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}

        {data.recommendations.length > 0 && (
          <div className="skin-recommendations">
            <h5>💊 护理建议</h5>
            <ul>
              {data.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="skin-timestamp">
        生成时间：{new Date(data.generated_at).toLocaleString('zh-CN')}
      </div>
    </div>
  );
}
