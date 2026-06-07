import { useEffect, useState, useRef, useCallback } from 'react';
import { InterruptCardData } from '../types/cards';

interface Props {
  data: InterruptCardData;
  onReply: (option: string) => void;
}

export function InterruptCard({ data, onReply }: Props) {
  const [remaining, setRemaining] = useState(data.timeout_s);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const expiredRef = useRef(false);

  const handleOption = useCallback(
    (option: string) => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      onReply(option);
    },
    [onReply]
  );

  useEffect(() => {
    setRemaining(data.timeout_s);
    expiredRef.current = false;

    timerRef.current = setInterval(() => {
      setRemaining((prev) => {
        const next = prev - 1;
        if (next <= 0 && !expiredRef.current) {
          expiredRef.current = true;
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          onReply(data.options[0] || '');
        }
        return next;
      });
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [data.timeout_s, data.options, onReply]);

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const timeDisplay = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  const isLow = remaining <= 30;

  return (
    <div className="card interrupt-card">
      <div className="card-header">
        <span className="card-type-badge">确认</span>
        <span className={`interrupt-countdown ${isLow ? 'countdown-low' : ''}`}>
          {timeDisplay}
        </span>
      </div>

      <p className="interrupt-question">{data.question}</p>

      <div className="interrupt-options-vertical">
        {data.options.map((opt, i) => (
          <button
            key={i}
            className="interrupt-option-btn"
            onClick={() => handleOption(opt)}
          >
            {opt}
          </button>
        ))}
      </div>

      <p className="interrupt-hint">
        超时将自动选择"{data.options[0] || '默认选项'}"
      </p>
    </div>
  );
}
