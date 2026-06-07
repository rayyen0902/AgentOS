import { CardPayload } from '../types/sse';
import { WorkshopCard } from './WorkshopCard';
import { SkinReportCard } from './SkinReportCard';
import { InterruptCard } from './InterruptCard';
import { ScheduleCard } from './ScheduleCard';

interface Props {
  card: CardPayload;
  onInterruptReply?: (option: string) => void;
}

export function CardRenderer({ card, onInterruptReply }: Props) {
  const defaultReply = (option: string) => {
    console.warn('InterruptCard reply not handled:', option);
  };

  switch (card.card_type) {
    case 'workshop_card':
      return <WorkshopCard data={card.data as any} />;
    case 'skin_report_card':
      return <SkinReportCard data={card.data as any} />;
    case 'interrupt_card':
      return (
        <InterruptCard
          data={card.data as any}
          onReply={onInterruptReply || defaultReply}
        />
      );
    case 'schedule_card':
      return <ScheduleCard data={card.data as any} />;
    default:
      return (
        <div className="card card-fallback">
          <div className="card-header">
            <span className="card-type-badge">{card.card_type}</span>
          </div>
          <pre className="card-data">{JSON.stringify(card.data, null, 2)}</pre>
        </div>
      );
  }
}
