"""
product_crud + profile_query — 严格对应 Step 5 文档 5.6 / 5.7
"""
import json
import logging

from app.tools.models import (
    ProductCRUDInput,
    ProductCRUDOutput,
    ProductItem,
    ProfileQueryInput,
    ProfileQueryOutput,
)
from app.tools.embedding import embed_single
from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# 5.6 product_crud — 产品录入/查询
# ============================================================

_PRODUCT_SELECT = "id, name, brand, category, ingredients, description"

def _row_to_product_item(row) -> ProductItem:
    ingredients = row.get("ingredients")
    if isinstance(ingredients, str):
        try:
            ingredients = json.loads(ingredients)
        except (json.JSONDecodeError, TypeError):
            ingredients = []
    return ProductItem(
        id=row["id"],
        name=row.get("name") or "",
        brand=row.get("brand") or "",
        category=row.get("category") or "",
        ingredients=ingredients or [],
        description=row.get("description") or "",
    )


async def product_crud(input: ProductCRUDInput) -> ProductCRUDOutput:
    """
    产品 CRUD — Step 5 文档 5.6
    支持 5 种 action: create | read | update | list | search
    create/update: 写入后触发 Embedding 生成（异步）
    """
    action = input.action
    tenant_id = input.tenant_id
    data = input.data
    product_id = input.product_id

    try:
        if action == "create":
            return await _product_create(tenant_id, data)

        elif action == "read":
            return await _product_read(product_id)

        elif action == "update":
            return await _product_update(product_id, data)

        elif action == "list":
            return await _product_list(tenant_id)

        elif action == "search":
            return await _product_search(tenant_id, input.query)

        else:
            return ProductCRUDOutput(
                success=False,
                action=action,
                error=f"Unknown action: {action}",
            )

    except Exception as e:
        logger.error(f"[product_crud] action={action} failed: {e}")
        raise  # 异常传播至 registry 层重试，兜底在 registry 层


async def _product_create(tenant_id: int, data: dict) -> ProductCRUDOutput:
    name = data.get("name", "")
    brand = data.get("brand", "")
    category = data.get("category", "")
    ingredients = json.dumps(data.get("ingredients", []), ensure_ascii=False)
    description = data.get("description", "")

    row = await db.fetchrow(
        """INSERT INTO products (tenant_id, name, brand, category, ingredients, description)
           VALUES ($1, $2, $3, $4, $5, $6)
           RETURNING id""",
        tenant_id, name, brand, category, ingredients, description,
    )
    new_id = row["id"]

    # 异步触发 Embedding 生成
    import asyncio
    asyncio.create_task(_update_product_embedding(new_id, name + " " + description))

    return ProductCRUDOutput(
        success=True,
        action="create",
        products=[ProductItem(id=new_id, name=name, brand=brand, category=category,
                               ingredients=data.get("ingredients", []), description=description)],
        affected_rows=1,
    )


async def _product_read(product_id: int) -> ProductCRUDOutput:
    if not product_id:
        return ProductCRUDOutput(success=False, action="read", error="product_id is required")

    row = await db.fetchrow(
        f"SELECT {_PRODUCT_SELECT} FROM products WHERE id = $1", product_id
    )
    if not row:
        return ProductCRUDOutput(success=False, action="read", error=f"Product {product_id} not found")

    return ProductCRUDOutput(
        success=True,
        action="read",
        products=[_row_to_product_item(row)],
        affected_rows=1,
    )


async def _product_update(product_id: int, data: dict) -> ProductCRUDOutput:
    if not product_id:
        return ProductCRUDOutput(success=False, action="update", error="product_id is required")

    updates = []
    params = []
    idx = 1

    for field in ["name", "brand", "category", "description"]:
        if field in data:
            updates.append(f"{field} = ${idx}")
            params.append(data[field])
            idx += 1

    if "ingredients" in data:
        updates.append(f"ingredients = ${idx}")
        params.append(json.dumps(data["ingredients"], ensure_ascii=False))
        idx += 1

    if not updates:
        return ProductCRUDOutput(success=False, action="update", error="No fields to update")

    params.append(product_id)
    result = await db.execute(
        f"UPDATE products SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )

    # 异步重新生成 Embedding
    name = data.get("name", "")
    desc = data.get("description", "")
    if name or desc:
        import asyncio
        asyncio.create_task(_update_product_embedding(product_id, name + " " + desc))

    return ProductCRUDOutput(
        success=True,
        action="update",
        affected_rows=1,
    )


async def _product_list(tenant_id: int) -> ProductCRUDOutput:
    rows = await db.fetch(
        f"SELECT {_PRODUCT_SELECT} FROM products WHERE tenant_id = $1 ORDER BY id DESC LIMIT 100",
        tenant_id,
    )
    products = [_row_to_product_item(r) for r in rows]
    return ProductCRUDOutput(
        success=True,
        action="list",
        products=products,
        affected_rows=len(products),
    )


async def _product_search(tenant_id: int, query: str | None) -> ProductCRUDOutput:
    if not query:
        return await _product_list(tenant_id)

    rows = await db.fetch(
        f"""SELECT {_PRODUCT_SELECT} FROM products
            WHERE tenant_id = $1
              AND (name ILIKE $2 OR brand ILIKE $2 OR description ILIKE $2)
            LIMIT 20""",
        tenant_id, f"%{query}%",
    )
    products = [_row_to_product_item(r) for r in rows]
    return ProductCRUDOutput(
        success=True,
        action="search",
        products=products,
        affected_rows=len(products),
    )


async def _update_product_embedding(product_id: int, text: str) -> None:
    """异步生成并更新产品 embedding 向量"""
    try:
        vec = await embed_single(text)
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
        await db.execute(
            "UPDATE products SET embedding = $1 WHERE id = $2",
            vec_str, product_id,
        )
        logger.info(f"[product_crud] embedding updated for product {product_id}")
    except Exception as e:
        logger.error(f"[product_crud] embedding update failed for product {product_id}: {e}")


# ============================================================
# 5.7 profile_query — 用户肤质/档案查询
# ============================================================

async def profile_query(input: ProfileQueryInput) -> ProfileQueryOutput:
    """
    用户肤质/档案查询 — Step 5 文档 5.7
    兜底: 返回空 profile，Agent 改走问卷路径
    """
    try:
        user_id = input.user_id
        include = input.include

        # 查询 skin_profiles 表
        skin_type = None
        skin_concerns: list[str] = []
        allergies: list[str] = []

        if "skin_type" in include or "concerns" in include or "allergies" in include:
            try:
                row = await db.fetchrow(
                    "SELECT skin_type, concerns, allergies FROM skin_profiles WHERE user_id = $1",
                    user_id,
                )
                if row:
                    skin_type = row.get("skin_type")

                    concerns = row.get("concerns")
                    if concerns:
                        skin_concerns = json.loads(concerns) if isinstance(concerns, str) else concerns

                    allergy_data = row.get("allergies")
                    if allergy_data:
                        allergies = json.loads(allergy_data) if isinstance(allergy_data, str) else allergy_data
            except Exception as e:
                logger.warning(f"[profile_query] skin_profiles fetch failed: {e}")

        # 查询 user_products 表（用户当前在用的产品）
        current_products: list[dict] = []
        if "current_products" in include:
            try:
                rows = await db.fetch(
                    """SELECT up.id, p.name, p.brand, p.category, up.usage_frequency
                       FROM user_products up
                       JOIN products p ON up.product_id = p.id
                       WHERE up.user_id = $1
                       ORDER BY up.updated_at DESC
                       LIMIT 20""",
                    user_id,
                )
                for r in rows:
                    current_products.append({
                        "id": r["id"],
                        "name": r.get("name") or "",
                        "brand": r.get("brand") or "",
                        "category": r.get("category") or "",
                        "usage_frequency": r.get("usage_frequency") or "",
                    })
            except Exception as e:
                logger.warning(f"[profile_query] user_products fetch failed: {e}")

        # 计算 profile_completeness (0.0-1.0)
        completeness = _calc_completeness(skin_type, skin_concerns, allergies, current_products)

        return ProfileQueryOutput(
            skin_type=skin_type,
            skin_concerns=skin_concerns,
            allergies=allergies,
            current_products=current_products,
            profile_completeness=completeness,
        )

    except Exception as e:
        logger.error(f"[profile_query] failed: {e}")
        raise  # 异常传播至 registry 层重试，兜底在 registry 层


def _calc_completeness(
    skin_type: str | None,
    skin_concerns: list[str],
    allergies: list[str],
    current_products: list[dict],
) -> float:
    """
    计算 profile 完整度 (0.0-1.0)
    每个维度权重均等:
      - skin_type: 0.25
      - skin_concerns: 0.25
      - allergies: 0.25
      - current_products: 0.25
    """
    score = 0.0
    if skin_type:
        score += 0.25
    if skin_concerns:
        score += 0.25
    if allergies:
        score += 0.25
    if current_products:
        score += 0.25
    return score
