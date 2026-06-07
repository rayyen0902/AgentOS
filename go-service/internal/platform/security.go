package platform

import (
	"crypto/hmac"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
)

// --- WeCom signature verification (doc section 7.2) ---

// VerifyWeComSignature verifies the WeCom SHA1 signature.
//
// Algorithm (per WeCom docs, doc section 7.2):
//  1. Sort token, timestamp, nonce, echostr lexicographically
//  2. Concatenate into a single string
//  3. SHA1 hash
//  4. Constant-time compare with msg_signature
func VerifyWeComSignature(token, timestamp, nonce, echostr, msgSignature string) bool {
	if token == "" {
		return false
	}
	strs := []string{token, timestamp, nonce, echostr}
	sort.Strings(strs)
	joined := strings.Join(strs, "")
	h := sha1.New()
	h.Write([]byte(joined))
	computed := hex.EncodeToString(h.Sum(nil))
	return hmac.Equal([]byte(computed), []byte(msgSignature))
}

// --- WeCom AES helpers ---

const aesBlockSize = 32

// pkcs7Unpad removes PKCS7 padding from decrypted data.
func pkcs7Unpad(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("pkcs7: empty data")
	}
	padLen := int(data[len(data)-1])
	if padLen > aesBlockSize || padLen == 0 || padLen > len(data) {
		return nil, fmt.Errorf("pkcs7: invalid padding length %d (data len %d)", padLen, len(data))
	}
	for i := 0; i < padLen; i++ {
		if data[len(data)-1-i] != byte(padLen) {
			return nil, fmt.Errorf("pkcs7: invalid padding")
		}
	}
	return data[:len(data)-padLen], nil
}

// --- Douyin HMAC-SHA256 verification (doc section 7.2) ---

// VerifyDouyinSignature verifies HMAC-SHA256(app_secret + timestamp + nonce + body).
// The body should be the raw POST body bytes.
func VerifyDouyinSignature(appSecret, timestamp, nonce string, body []byte, signature string) bool {
	mac := hmac.New(sha256.New, []byte(appSecret))
	mac.Write([]byte(appSecret))
	mac.Write([]byte(timestamp))
	mac.Write([]byte(nonce))
	mac.Write(body)
	computed := hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(computed), []byte(signature))
}

// --- Xiaohongshu RSA verification placeholder (doc section 7.2) ---

// XHS verifier type — production should use the official XHS SDK.
type XHSVerifier func(payload []byte, signature string, publicKey string) bool

// DefaultXHSVerifier is a placeholder; production should use the official XHS SDK.
func DefaultXHSVerifier(payload []byte, signature string, publicKey string) bool {
	// In production, replace with the official SDK:
	//   return xhs_sdk.VerifySignature(payload, signature, publicKey)
	return false
}
