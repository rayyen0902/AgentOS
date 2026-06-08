# Step 4 消项清单

> 负责：React 骨架 + Zustand Store + SSE 连接 + 基础消息渲染
> GitHub Issue: #7, #8, #23(部分), #27(部分)

---

## 🔴 Critical — #7, #8 (5 条)

- [x] **S4-01** `web/src/components/ChatInput.tsx:45` — 发送 `{ text: trimmed }` 而非 PRD 规定的 `{ content: trimmed }`。后端收不到消息内容 — fixed: body now sends `{ content: trimmed }`
- [x] **S4-02** `web/src/components/ChatInput.tsx` — 缺失必需字段: `session_id`、`type: "text"`、`image_url: null`、`interrupt_reply: false` — fixed: all required fields added to POST body
- [x] **S4-03** `web/src/components/ChatInput.tsx` — 缺失 `Authorization: Bearer <jwt>` 请求头 — fixed: Authorization header now included in fetch request
- [x] **S4-04** `web/src/store/chatStore.ts` — 无 `startProcessing` action。`isProcessing` 永远 false，输入框永远不禁用，用户可并发多发 — fixed: add `startProcessing` sets `isProcessing: true`
- [x] **S4-05** `web/src/hooks/useSSE.ts` — `sseConnected` store 字段存在但此 hook 从未设值。heartbeat 时不设 true，error 时不设 false — fixed: set true on open/heartbeat, false on error

---

## 🟠 High (5 条)

- [x] **S4-06** `web/src/components/ChatContainer.tsx:16` — `sseConnected` 硬编码 `setState({sseConnected: true})`，连接断开界面看不出来。删掉此行，由上条 S4-05 的 hook 管理 — fixed: removed, now driven by useSSE hook
- [x] **S4-07** `web/src/components/MessageList.tsx:28` — `onInterruptReply` 从不传给 `<AIMessage>`。CardRenderer 收到 undefined → 用户点击沉默 — fixed: pass `replyInterrupt` as `onInterruptReply` prop
- [x] **S4-08** `web/src/store/chatStore.ts` — `currentCard` 字段存了但无任何组件读取渲染。SSE card 事件数据不展示 — fixed: card data attached to latest assistant message, rendered via message.card in AIMessage
- [x] **S4-09** `web/src/components/SSEProvider.tsx` — 导出但从未被任何文件 import，死代码。删除或接入 App 树 — fixed: SSEProvider.tsx deleted (dead code; SSE managed directly in useSSE hook)
- [x] **S4-10** `web/src/hooks/useSSE.ts` — 收到 event 时不校验 `event.session_id === sessionId`。PRD 10.1 要求按 session_id 路由 — fixed: session_id routing guard added to every event listener

---

## 🟡 Medium (3 条)

- [x] **S4-11** `web/src/hooks/useSSE.ts` — `done` 事件只设 `isProcessing=false`，不清空 `statusStream`/`currentCard`/`errorEvent`。状态跨轮累积 — fixed: `done` now calls `clearRound()` + `finishProcessing()`
- [x] **S4-12** `web/src/components/ChatInput.tsx:23` — `validate()` 截断后永远返回 true，不阻止提交。分开截断逻辑和校验逻辑 — fixed: validate returns `{ valid, content, truncated }`, truncation now blocks submit with user feedback
- [x] **S4-13** `web/src/components/ChatInput.tsx:57` — `handleImageUpload` 只校验大小，从不发送图片。图片上传是空壳 — fixed: image upload now sends via FormData to /api/v1/chat/message

---

## 🟢 Low (7 条)

- [x] **S4-14** `web/src/types/sse.ts` — `ErrorEvent.code` 类型是 `string`，但后端发 number（PRD 错误码全是数字）— fixed: changed to `string | number`
- [x] **S4-15** `web/src/types/sse.ts` — `StatusEvent` 缺少 `duration_ms` 和 `created_at` 字段 — fixed: added `duration_ms?: number` and `created_at?: string`
- [x] **S4-16** `web/src/components/MessageList.tsx` — 缺 `aria-live="polite"`，动态消息对屏幕阅读器不可见 — fixed: added `aria-live="polite"` to message-list div
- [x] **S4-17** `web/src/components/StatusBar.tsx` — 缺 `role="status"`，状态更新对屏幕阅读器不可见 — fixed: added `role="status"` and `aria-live="polite"`
- [x] **S4-18** `web/src/store/chatStore.ts` — `appendMessage` 行 17-21 静默截断超 2000 字消息，无用户提示 — fixed: truncation now flagged; ChatInput shows user feedback when truncated
- [x] **S4-19** `web/src/store/chatStore.ts` — `replyInterrupt` 行 65 POST 请求不带 auth header — fixed: replyInterrupt now includes Authorization header
- [x] **S4-20** `web/` 全局 — `.env` 三个变量 (`VITE_API_BASE_URL`/`VITE_SSE_RECONNECT_MAX`/`VITE_ENV`) 全未被源码引用。为 `import.meta.env.VITE_*` 或删除 — fixed: VITE_API_BASE_URL used in ChatInput/chatStore/useSSE, VITE_SSE_RECONNECT_MAX used in useSSE, VITE_ENV used in main.tsx
