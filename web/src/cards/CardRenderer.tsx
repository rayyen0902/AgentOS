import { TypedCard } from './narrowCard';
import { WorkshopCard } from './WorkshopCard';
import { SkinReportCard } from './SkinReportCard';
import { InterruptCard } from './InterruptCard';
import { ScheduleCard } from './ScheduleCard';

interface Props {
  card: TypedCard;
  onInterruptReply?: (option: string) => void;
}

export function CardRenderer({ card, onInterruptReply }: Props) {
  const defaultReply = (option: string) => {
    console.warn('InterruptCard reply not handled:', option);
  };
  const reply = onInterruptReply || defaultReply;

  switch (card.card_type) {
    case 'workshop_card':
      return <WorkshopCard data={card.data} />;
    case 'skin_report_card':
      return <SkinReportCard data={card.data} />;
    case 'interrupt_card':
      return <InterruptCard data={card.data} onReply={reply} />;
    case 'schedule_card':
      return <ScheduleCard data={card.data} />;
  }
}
