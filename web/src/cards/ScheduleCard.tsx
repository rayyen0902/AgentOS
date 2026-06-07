import { ScheduleCardData, ScheduleSlot } from '../types/cards';

interface Props {
  data: ScheduleCardData;
}

function SlotSection({ slot }: { slot: ScheduleSlot }) {
  return (
    <div className="schedule-slot">
      <div className="schedule-slot-header">
        <span className="schedule-time">{slot.time}</span>
        <span className="schedule-label">{slot.label}</span>
      </div>

      <ol className="schedule-steps">
        {slot.steps.map((step, i) => (
          <li key={i} className="schedule-step">
            <span className="step-product">{step.product}</span>
            <span className="step-action">{step.step}</span>
            {step.note && <span className="step-note">{step.note}</span>}
          </li>
        ))}
      </ol>

      {slot.notes.length > 0 && (
        <div className="schedule-notes">
          {slot.notes.map((n, i) => (
            <p key={i} className="schedule-note">📌 {n}</p>
          ))}
        </div>
      )}
    </div>
  );
}

export function ScheduleCard({ data }: Props) {
  return (
    <div className="card schedule-card">
      <div className="card-header">
        <span className="card-type-badge">日程</span>
      </div>

      <SlotSection slot={data.morning} />
      <SlotSection slot={data.evening} />
    </div>
  );
}
