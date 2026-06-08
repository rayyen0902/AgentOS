package platform

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestOpenIDToUserID(t *testing.T) {
	// --- Same input → same output (determinism) ---
	a := openIDToUserID("user_abc", 1)
	b := openIDToUserID("user_abc", 1)
	assert.Equal(t, a, b, "same input must produce same output")

	// --- Different tenantID → different output ---
	c1 := openIDToUserID("user_abc", 1)
	c2 := openIDToUserID("user_abc", 2)
	assert.NotEqual(t, c1, c2, "different tenantID must produce different output")

	// --- Result = 0 → promote to 1 ---
	// tenantID=0 and empty openID → h starts at 0, loop never runs, h stays 0
	zero := openIDToUserID("", 0)
	assert.Equal(t, int64(1), zero, "zero result must be promoted to 1")

	// --- Negative → absolute value ---
	// Use math.MaxInt64 as tenantID with a single character to cause signed overflow
	neg := openIDToUserID("z", math.MaxInt64)
	assert.Greater(t, neg, int64(0), "result must be positive even after overflow")

	// --- Hash determinism across calls ---
	results := make([]int64, 10)
	for i := 0; i < 10; i++ {
		results[i] = openIDToUserID("deterministic_test", 42)
	}
	for i := 1; i < len(results); i++ {
		assert.Equal(t, results[0], results[i], "hash must be deterministic across calls")
	}
}

func TestNormalizeWeCom(t *testing.T) {
	msg := &WeComDecryptedMsg{
		ToUserName:   "gh_abc",
		FromUserName: "openid_wecom_001",
		CreateTime:   1234567890,
		MsgType:      "text",
		Content:      "Hello from WeCom",
		MsgID:        1001,
		AgentID:      1000002,
	}

	result := NormalizeWeCom(msg, 1, "openid_wecom_001")

	expectedUserID := openIDToUserID("openid_wecom_001", 1)
	assert.Equal(t, expectedUserID, result.UserID)
	assert.Equal(t, int64(1), result.TenantID)
	assert.Equal(t, "wecom", result.Platform)
	assert.Equal(t, "text", result.Message.Type)
	assert.Equal(t, "Hello from WeCom", result.Message.Content)
	assert.Nil(t, result.Message.ImageURL)
	assert.Equal(t, "conv_wecom_openid_wecom_001_1", result.SessionID)
	assert.NotNil(t, result.AgentState)
}

func TestNormalizeWeCom_ImageMessage(t *testing.T) {
	msg := &WeComDecryptedMsg{
		ToUserName:   "gh_abc",
		FromUserName: "openid_wecom_img",
		CreateTime:   1234567890,
		MsgType:      "image",
		Content:      "",
		MsgID:        1002,
		AgentID:      1000002,
		PicURL:       "https://example.com/img.jpg",
	}

	result := NormalizeWeCom(msg, 1, "openid_wecom_img")

	assert.Equal(t, "image", result.Message.Type)
	assert.NotNil(t, result.Message.ImageURL)
	assert.Equal(t, "https://example.com/img.jpg", *result.Message.ImageURL)
}

func TestNormalizeDouyin(t *testing.T) {
	body := &DouyinWebhookBody{
		ToUserID:   "agent_001",
		FromUserID: "user_douyin_001",
		MsgType:    "text",
		Content: DouyinText{
			Text: "Hello from Douyin",
		},
		Timestamp: 1234567890,
	}

	result := NormalizeDouyin(body, 2)

	expectedUserID := openIDToUserID("user_douyin_001", 2)
	assert.Equal(t, expectedUserID, result.UserID)
	assert.Equal(t, int64(2), result.TenantID)
	assert.Equal(t, "douyin", result.Platform)
	assert.Equal(t, "text", result.Message.Type)
	assert.Equal(t, "Hello from Douyin", result.Message.Content)
	assert.Equal(t, "conv_douyin_user_douyin_001_2", result.SessionID)
	assert.NotNil(t, result.AgentState)
}

func TestNormalizeXHS(t *testing.T) {
	body := &XHSWebhookBody{
		MsgType:    "text",
		FromUserID: "user_xhs_001",
		ToUserID:   "agent_001",
		Content:    "Hello from XHS",
		MsgID:      "msg_001",
	}

	result := NormalizeXHS(body, 3)

	expectedUserID := openIDToUserID("user_xhs_001", 3)
	assert.Equal(t, expectedUserID, result.UserID)
	assert.Equal(t, int64(3), result.TenantID)
	assert.Equal(t, "xhs", result.Platform)
	assert.Equal(t, "text", result.Message.Type)
	assert.Equal(t, "Hello from XHS", result.Message.Content)
	assert.Equal(t, "conv_xhs_user_xhs_001_3", result.SessionID)
	assert.NotNil(t, result.AgentState)
}
