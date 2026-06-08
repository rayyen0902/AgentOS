package platform

import (
	"fmt"
)

// NormalizeWeCom converts a decrypted WeCom message to the internal format.
// Fields used as documented in section 7A:
//   - FromUserName becomes user_id (mapped via openid)
//   - Content maps to message.content
//   - MsgType determines message.type (text/image)
func NormalizeWeCom(msg *WeComDecryptedMsg, tenantID int64, openID string) *InboundMessage {
	userID := openIDToUserID(openID, tenantID)
	msgType := "text"
	var imageURL *string
	if msg.MsgType == "image" {
		msgType = "image"
		if msg.PicURL != "" {
			imageURL = &msg.PicURL
		}
	}
	sessionID := fmt.Sprintf("conv_wecom_%s_%d", openID, tenantID)
	return &InboundMessage{
		SessionID: sessionID,
		UserID:    userID,
		TenantID:  tenantID,
		Platform:  "wecom",
		Message: MessageBody{
			Type:     msgType,
			Content:  msg.Content,
			ImageURL: imageURL,
		},
		AgentState: map[string]interface{}{},
	}
}

// NormalizeDouyin converts a Douyin webhook body to the internal format.
// Fields used: FromUserID → user_id, Content.Text → message.content.
func NormalizeDouyin(body *DouyinWebhookBody, tenantID int64) *InboundMessage {
	userID := openIDToUserID(body.FromUserID, tenantID)
	msgType := "text"
	if body.MsgType != "text" {
		msgType = body.MsgType
	}
	sessionID := fmt.Sprintf("conv_douyin_%s_%d", body.FromUserID, tenantID)
	return &InboundMessage{
		SessionID: sessionID,
		UserID:    userID,
		TenantID:  tenantID,
		Platform:  "douyin",
		Message: MessageBody{
			Type:    msgType,
			Content: body.Content.Text,
		},
		AgentState: map[string]interface{}{},
	}
}

// NormalizeXHS converts a Xiaohongshu webhook body to the internal format.
// Fields used: FromUserID → user_id, Content → message.content.
func NormalizeXHS(body *XHSWebhookBody, tenantID int64) *InboundMessage {
	userID := openIDToUserID(body.FromUserID, tenantID)
	msgType := "text"
	if body.MsgType != "text" {
		msgType = body.MsgType
	}
	sessionID := fmt.Sprintf("conv_xhs_%s_%d", body.FromUserID, tenantID)
	return &InboundMessage{
		SessionID: sessionID,
		UserID:    userID,
		TenantID:  tenantID,
		Platform:  "xhs",
		Message: MessageBody{
			Type:    msgType,
			Content: body.Content,
		},
		AgentState: map[string]interface{}{},
	}
}

// openIDToUserID maps an openid to a deterministic numeric user_id.
// S3-07: Include tenant_id in hash to prevent cross-tenant collisions.
func openIDToUserID(openID string, tenantID int64) int64 {
	var h int64 = tenantID
	for _, c := range openID {
		h = h*31 + int64(c)
	}
	if h < 0 {
		h = -h
	}
	if h == 0 {
		h = 1
	}
	return h
}
