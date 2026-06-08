import { CardPayload } from '../types/sse';
import { CardRenderer as InnerRenderer } from './CardRenderer';
import { narrowCard } from './narrowCard';

interface Props {
  card: CardPayload;
  onInterruptReply?: (option: string) => void;
}

export function SafeCardRenderer({ card, onInterruptReply }: Props) {
  const typed = narrowCard(card);
  if (!typed) {
    return (
      <div className="card card-fallback">
        <div className="card-header">
          <span className="card-type-badge">未知类型: {card.card_type}</span>
        </div>
        <pre className="card-data">{JSON.stringify(card.data, null, 2)}</pre>
      </div>
    );
  }
  return <InnerRenderer card={typed} onInterruptReply={onInterruptReply} />;
}
