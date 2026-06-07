import { useState, useEffect, FormEvent } from 'react';

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

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [prodRes, conflRes] = await Promise.all([
        fetch('/api/v1/admin/knowledge/products'),
        fetch('/api/v1/admin/knowledge/conflicts'),
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
  };

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
      const res = await fetch('/api/v1/admin/knowledge/products', {
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
      const res = await fetch('/api/v1/admin/knowledge/conflicts', {
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
      const res = await fetch(`/api/v1/admin/knowledge/conflicts/${id}`, {
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

      <div className="knowledge-tabs">
        <button
          className={`tab-btn ${tab === 'products' ? 'active' : ''}`}
          onClick={() => setTab('products')}
        >
          产品录入
        </button>
        <button
          className={`tab-btn ${tab === 'ingredients' ? 'active' : ''}`}
          onClick={() => setTab('ingredients')}
        >
          成分管理
        </button>
        <button
          className={`tab-btn ${tab === 'conflicts' ? 'active' : ''}`}
          onClick={() => setTab('conflicts')}
        >
          冲突规则
        </button>
      </div>

      {tab === 'products' && (
        <div className="knowledge-section">
          <h3>产品录入</h3>
          <form className="knowledge-form" onSubmit={addProduct}>
            <label>名称 <input type="text" value={newProduct.name} onChange={(e) => setNewProduct((f) => ({ ...f, name: e.target.value }))} required /></label>
            <label>品牌 <input type="text" value={newProduct.brand} onChange={(e) => setNewProduct((f) => ({ ...f, brand: e.target.value }))} required /></label>
            <label>分类 <input type="text" value={newProduct.category} onChange={(e) => setNewProduct((f) => ({ ...f, category: e.target.value }))} required /></label>
            <label>价格 <input type="number" value={newProduct.price || ''} onChange={(e) => setNewProduct((f) => ({ ...f, price: Number(e.target.value) }))} required /></label>
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
              {products.map((p) => (
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
            </tbody>
          </table>
        </div>
      )}

      {tab === 'ingredients' && (
        <div className="knowledge-section">
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
        <div className="knowledge-section">
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
              {conflicts.map((c) => (
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
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
