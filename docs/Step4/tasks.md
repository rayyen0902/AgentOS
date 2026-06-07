# Step 4 消项清单

> 你负责：React 骨架 + Zustand Store + SSE 连接 + 基础消息渲染

---

## #7 【Critical】前端消息请求字段名错误 + 缺必需字段 + 缺 auth header

**文件**: `web/src/components/ChatInput.tsx:45`

**修复**:
1. `{ text: trimmed }` → `{ content: trimmed }`（PRD 19.2 规定的字段名）
2. 补充 `session_id`、`type: "text"`、`image_url: null`、`interrupt_reply: false`
3. 补充 `Authorization: Bearer <jwt>` 请求头

---

## #8 【Critical】isProcessing 从未设为 true + sseConnected 硬编码 + 中断回调断链 + currentCard 不渲染

**文件**: 多个

| 文件 | 问题 | 修复 |
|------|------|------|
| `store/chatStore.ts` | 无 `startProcessing` action | 新增 action，ChatInput 发送时调用 |
| `components/ChatContainer.tsx:16` | `sseConnected` 硬编码 true | 删掉此行，由 useSSE hook 管理 |
| `hooks/useSSE.ts` | hook 从未设 sseConnected | heartbeat 时设 true，error 时设 false |
| `components/MessageList.tsx:28` | 不给 AIMessage 传 onInterruptReply | 从 store 取 replyInterrupt 传入 |
| `store/chatStore.ts` | currentCard 存了无组件读 | 在 AIMessage 或 ChatContainer 中渲染 currentCard |

---

## #23 部分归属 Step 4: SSEProvider 死代码 + useSSE 不校验 session_id

**修复**:
1. 删除 `SSEProvider.tsx`（死代码，从未 import）或接入 App 树
2. `hooks/useSSE.ts` 收到 event 时校验 `event.session_id === sessionId`

---

## #27 部分归属 Step 4: 类型 + A11y + 环境变量

| 文件 | 问题 | 修复 |
|------|------|------|
| `types/sse.ts` | `ErrorEvent.code` 类型 string | 改为 `number` |
| `components/MessageList.tsx` | 缺 `aria-live` | 加 `aria-live="polite"` |
| `components/StatusBar.tsx` | 缺 `role="status"` | 加 `role="status"` |
| `components/ChatInput.tsx` | 图片上传空壳 | 实现实际上传逻辑或标注 TODO |
| `components/ChatInput.tsx` | `validate()` 永远返回 true | 分开截断逻辑和校验逻辑 |
| `.env` | 3 个变量全未引用 | 在代码中引用或用 `import.meta.env` |

---

## 关联：跨 Step 协调

- `hooks/useSSE.ts` 的 `done` 事件处理需清空 statusStream/currentCard（与 Store action 配合）
- 消息内容需前端 2000 字截断（PRD 20.3）
