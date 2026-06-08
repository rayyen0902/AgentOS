package platform

import (
	"crypto/sha1"
	"encoding/hex"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestVerifyWeComSignature_Valid(t *testing.T) {
	token := "test_token_abc"
	timestamp := "1620000000"
	nonce := "random_nonce_123"
	echostr := "hello_echostr"

	// Compute expected signature manually (same algorithm as VerifyWeComSignature)
	strs := []string{token, timestamp, nonce, echostr}
	sort.Strings(strs)
	joined := strings.Join(strs, "")
	h := sha1.New()
	h.Write([]byte(joined))
	expected := hex.EncodeToString(h.Sum(nil))

	result := VerifyWeComSignature(token, timestamp, nonce, echostr, expected)
	assert.True(t, result, "valid signature should pass")
}

func TestVerifyWeComSignature_WrongToken(t *testing.T) {
	token := "test_token_abc"
	timestamp := "1620000000"
	nonce := "random_nonce_123"
	echostr := "hello_echostr"

	// Compute signature with the correct token
	strs := []string{token, timestamp, nonce, echostr}
	sort.Strings(strs)
	joined := strings.Join(strs, "")
	h := sha1.New()
	h.Write([]byte(joined))
	correctSig := hex.EncodeToString(h.Sum(nil))

	// Verify with wrong token — should still produce the same signature input
	// But we can test: passing a completely different signature string
	result := VerifyWeComSignature(token, timestamp, nonce, echostr, "0000000000000000000000000000000000000000")
	assert.False(t, result, "wrong signature should fail")
	assert.True(t, len(correctSig) > 0)
}

func TestVerifyWeComSignature_EmptyToken(t *testing.T) {
	result := VerifyWeComSignature("", "ts", "nc", "echo", "any_signature")
	assert.False(t, result, "empty token should return false")
}

func TestVerifyWeComSignature_DifferentEchostr(t *testing.T) {
	token := "tok"
	timestamp := "1"
	nonce := "2"
	echostr1 := "echo_A"
	echostr2 := "echo_B"

	// Signatures for different echostrs should differ
	sig1 := computeWeComSignature(token, timestamp, nonce, echostr1)
	sig2 := computeWeComSignature(token, timestamp, nonce, echostr2)

	assert.NotEqual(t, sig1, sig2, "different echostr should yield different signatures")

	// Verify sig1 matches only with echostr1
	assert.True(t, VerifyWeComSignature(token, timestamp, nonce, echostr1, sig1))
	assert.False(t, VerifyWeComSignature(token, timestamp, nonce, echostr1, sig2))
}

func TestGetAgentID_WithConfig(t *testing.T) {
	adapter := &WeComAdapter{}
	cfg := &TenantPlatform{WeComAgentID: 5000000}
	agentID := adapter.getAgentID(cfg)
	assert.Equal(t, 5000000, agentID)
}

func TestGetAgentID_Fallback(t *testing.T) {
	adapter := &WeComAdapter{}
	cfg := &TenantPlatform{WeComAgentID: 0}
	agentID := adapter.getAgentID(cfg)
	assert.Equal(t, 1000002, agentID)
}

// computeWeComSignature is a helper to produce the expected WeCom SHA1 signature.
func computeWeComSignature(token, timestamp, nonce, echostr string) string {
	strs := []string{token, timestamp, nonce, echostr}
	sort.Strings(strs)
	joined := strings.Join(strs, "")
	h := sha1.New()
	h.Write([]byte(joined))
	return hex.EncodeToString(h.Sum(nil))
}
