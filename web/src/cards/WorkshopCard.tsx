import { WorkshopCardData } from '../types/cards';

interface Props {
  data: WorkshopCardData;
}

export function WorkshopCard({ data }: Props) {
  return (
    <div className="card workshop-card">
      <div className="card-header">
        <span className="card-type-badge">配药师推荐</span>
      </div>

      <div className="workshop-products">
        {data.products.map((product) => (
          <div
            key={product.id}
            className="workshop-product"
            onClick={() => {
              window.open(`/product/${product.id}`, '_blank');
            }}
          >
            <img
              className="product-image"
              src={product.image_url}
              alt={product.name}
              loading="lazy"
            />
            <div className="product-info">
              <h4 className="product-name">{product.name}</h4>
              <span className="product-brand">{product.brand}</span>
              <span className="product-category">{product.category}</span>
              <span className="product-price">¥{product.price}</span>
              <p className="product-reason">{product.reason}</p>
              <div className="product-ingredients">
                {product.key_ingredients.map((ing) => (
                  <span key={ing} className="ingredient-chip">{ing}</span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {data.conflicts.length > 0 && (
        <div className="workshop-conflicts">
          <h5 className="conflict-title">⚠️ 成分冲突警告</h5>
          {data.conflicts.map((c, i) => (
            <div key={i} className="conflict-item">
              <span className="conflict-products">{c.product_a} + {c.product_b}</span>
              <span className="conflict-reason">{c.reason}</span>
            </div>
          ))}
        </div>
      )}

      {data.routine_tip && (
        <div className="workshop-tip">
          <span className="tip-label">💡 护肤小贴士</span>
          <p className="tip-text">{data.routine_tip}</p>
        </div>
      )}
    </div>
  );
}
