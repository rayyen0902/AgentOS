import { useState, useEffect, FormEvent, useCallback } from 'react';
import { adminFetch } from './api';

const PAGE_SIZE = 15;

interface Product {
  id: number;
  name: string;
  brand: string;
  category: string;
  price: number;
  ingredients: string[];
  image_url: string;
}

interface ConflictRule {
  id: number;
  ingredient_a: string;
  ingredient_b: string;
  reason: string;
}

export function AdminKnowledge() {
  const [tab, setTab] = useState<'products' | 'ingredients' | 'conflicts'>('products');
  const [products, setProducts] = useState<Product[]>([]);
  const [conflicts, setConflicts] = useState<ConflictRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // client-side pagination
  const [prodPage, setProdPage] = useState(1);
  const [conflictPage, setConflictPage] = useState(1);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [prodRes, conflRes] = await Promise.all([
        adminFetch('/api/v1/admin/knowledge/products'),
        adminFetch('/api/v1/admin/knowledge/conflicts'),
      ]);
      const prodData = await prodRes.json();
      const conflData = await conflRes.json();
      if (prodData.code === 0) setProducts(prodData.data || []);
      if (conflData.code === 0) setConflicts(conflData.data || []);
    } catch {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, []);

  const [newProduct, setNewProduct] = useState({
    name: '',
    brand: '',
    category: '',
    price: 0,
    ingredients: '',
    image_url: '',
  });
  const [newConflict, setNewConflict] = useState({
    ingredient_a: '',
    ingredient_b: '',
    reason: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const addProduct = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await adminFetch('/api/v1/admin/knowledge/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...newProduct,
          ingredients: newProduct.ingredients.split(',').map((s) => s.trim()).filter(Boolean),
        }),
      });
      const data = await res.json();
      if (data.code === 0) {
        setProducts((prev) => [...prev, data.data]);
        setNewProduct({ name: '', brand: '', category: '', price: 0, ingredients: '', image_url: '' });
      } else {
        setError(data.message || '添加失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setSubmitting(false);
    }
  };

  const addConflict = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await adminFetch('/api/v1/admin/knowledge/conflicts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConflict),
      });
      const data = await res.json();
      if (data.code === 0) {
        setConflicts((prev) => [...prev, data.data]);
        setNewConflict({ ingredient_a: '', ingredient_b: '', reason: '' });
      } else {
        setError(data.message || '添加失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setSubmitting(false);
    }
  };

  const deleteConflict = async (id: number) => {
    try {
      const res = await adminFetch(`/api/v1/admin/knowledge/conflicts/${id}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (data.code === 0) {
        setConflicts((prev) => prev.filter((c) => c.id !== id));
      } else {
        setError(data.message || '删除失败');
      }
    } catch {
      setError('网络错误');
    }
  };

  // Paginated slices
  const prodTotalPages = Math.max(1, Math.ceil(products.length / PAGE_SIZE));
  const prodSlice = products.slice((prodPage - 1) * PAGE_SIZE, prodPage * PAGE_SIZE);
  const conflTotalPages = Math.max(1, Math.ceil(conflicts.length / PAGE_SIZE));
  const conflSlice = conflicts.slice((conflictPage - 1) * PAGE_SIZE, conflictPage * PAGE_SIZE);

  // Reset pagination on tab change
  const onTabChange = (t: typeof tab) => {
    setTab(t);
    setProdPage(1);
    setConflictPage(1);
  };

  const Pager = ({
    page,
    total,
    onChange,
  }: {
    page: number;
    total: number;
    onChange: (p: number) => void;
  }) => (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ‹ 上一页
      </button>
      <span>
        {page} / {total}
      </span>
      <button disabled={page >= total} onClick={() => onChange(page + 1)}>
        下一页 ›
      </button>
    </div>
  );

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="admin-knowledge">
      <h2>知识管理</h2>
      {error && (
        <div className="admin-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="knowledge-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'products'}
          aria-controls="panel-products"
          className={`tab-btn ${tab === 'products' ? 'active' : ''}`}
          onClick={() => onTabChange('products')}
        >
          产品录入
        </button>
        <button
          role="tab"
          aria-selected={tab === 'ingredients'}
          aria-controls="panel-ingredients"
          className={`tab-btn ${tab === 'ingredients' ? 'active' : ''}`}
          onClick={() => onTabChange('ingredients')}
        >
          成分管理
        </button>
        <button
          role="tab"
          aria-selected={tab === 'conflicts'}
          aria-controls="panel-conflicts"
          className={`tab-btn ${tab === 'conflicts' ? 'active' : ''}`}
          onClick={() => onTabChange('conflicts')}
        >
          冲突规则
        </button>
      </div>

      {tab === 'products' && (
        <div className="knowledge-section" role="tabpanel" id="panel-products">
          <h3>产品录入</h3>
          <form className="knowledge-form" onSubmit={addProduct}>
            <label>名称 <input type="text" value={newProduct.name} onChange={(e) => setNewProduct((f) => ({ ...f, name: e.target.value }))} required /></label>
            <label>品牌 <input type="text" value={newProduct.brand} onChange={(e) => setNewProduct((f) => ({ ...f, brand: e.target.value }))} required /></label>
            <label>分类 <input type="text" value={newProduct.category} onChange={(e) => setNewProduct((f) => ({ ...f, category: e.target.value }))} required /></label>
            <label>价格 <input type="number" value={newProduct.price ?? ''} onChange={(e) => setNewProduct((f) => ({ ...f, price: Number(e.target.value) }))} required /></label>
            <label>成分（逗号分隔） <input type="text" value={newProduct.ingredients} onChange={(e) => setNewProduct((f) => ({ ...f, ingredients: e.target.value }))} /></label>
            <label>图片URL <input type="url" value={newProduct.image_url} onChange={(e) => setNewProduct((f) => ({ ...f, image_url: e.target.value }))} /></label>
            <button type="submit" disabled={submitting}>添加产品</button>
          </form>

          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>品牌</th>
                <th>分类</th>
                <th>价格</th>
                <th>成分</th>
              </tr>
            </thead>
            <tbody>
              {prodSlice.map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td>{p.name}</td>
                  <td>{p.brand}</td>
                  <td>{p.category}</td>
                  <td>¥{p.price}</td>
                  <td>
                    <div className="ingredient-tags">
                      {p.ingredients.map((ing) => (
                        <span key={ing} className="ingredient-chip-sm">{ing}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {prodSlice.length === 0 && (
                <tr><td colSpan={6} className="empty-cell">暂无产品</td></tr>
              )}
            </tbody>
          </table>
          {products.length > PAGE_SIZE && (
            <Pager page={prodPage} total={prodTotalPages} onChange={setProdPage} />
          )}
        </div>
      )}

      {tab === 'ingredients' && (
        <div className="knowledge-section" role="tabpanel" id="panel-ingredients">
          <h3>成分管理</h3>
          <p className="knowledge-hint">所有产品中使用的成分汇总（由产品录入自动更新）</p>
          <table className="admin-table">
            <thead>
              <tr><th>成分名</th><th>出现次数</th></tr>
            </thead>
            <tbody>
              {(() => {
                const freq: Record<string, number> = {};
                products.forEach((p) => p.ingredients.forEach((i) => { freq[i] = (freq[i] || 0) + 1; }));
                return Object.entries(freq).map(([name, count]) => (
                  <tr key={name}><td>{name}</td><td>{count}</td></tr>
                ));
              })()}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'conflicts' && (
        <div className="knowledge-section" role="tabpanel" id="panel-conflicts">
          <h3>冲突规则</h3>
          <form className="knowledge-form" onSubmit={addConflict}>
            <label>成分A <input type="text" value={newConflict.ingredient_a} onChange={(e) => setNewConflict((f) => ({ ...f, ingredient_a: e.target.value }))} required /></label>
            <label>成分B <input type="text" value={newConflict.ingredient_b} onChange={(e) => setNewConflict((f) => ({ ...f, ingredient_b: e.target.value }))} required /></label>
            <label>冲突原因 <input type="text" value={newConflict.reason} onChange={(e) => setNewConflict((f) => ({ ...f, reason: e.target.value }))} required /></label>
            <button type="submit" disabled={submitting}>添加冲突规则</button>
          </form>

          <table className="admin-table">
            <thead>
              <tr><th>ID</th><th>成分A</th><th>成分B</th><th>原因</th><th>操作</th></tr>
            </thead>
            <tbody>
              {conflSlice.map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td>
                  <td>{c.ingredient_a}</td>
                  <td>{c.ingredient_b}</td>
                  <td>{c.reason}</td>
                  <td>
                    <button className="btn-reject" onClick={() => deleteConflict(c.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              {conflSlice.length === 0 && (
                <tr><td colSpan={5} className="empty-cell">暂无冲突规则</td></tr>
              )}
            </tbody>
          </table>
          {conflicts.length > PAGE_SIZE && (
            <Pager page={conflictPage} total={conflTotalPages} onChange={setConflictPage} />
          )}
        </div>
      )}
    </div>
  );
}
