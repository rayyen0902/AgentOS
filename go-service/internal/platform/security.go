package platform

import (
	"crypto"
	"crypto/hmac"
	"crypto/rsa"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"sort"
	"strings"
)

// --- WeCom signature verification (doc section 7.2) ---

// VerifyWeComSignature verifies the WeCom SHA1 signature.
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
func VerifyDouyinSignature(appSecret, timestamp, nonce string, body []byte, signature string) bool {
	mac := hmac.New(sha256.New, []byte(appSecret))
	mac.Write([]byte(appSecret))
	mac.Write([]byte(timestamp))
	mac.Write([]byte(nonce))
	mac.Write(body)
	computed := hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(computed), []byte(signature))
}

// --- Xiaohongshu RSA verification (doc section 7.2) ---

// XHSVerifier type signature.
type XHSVerifier func(payload []byte, signature string, publicKeyPEM string) bool

// VerifyXHSRSA performs real RSA PKCS#1 v1.5 signature verification with SHA-256.
// S7-04: Now implements real RSA verification instead of returning false.
func VerifyXHSRSA(payload []byte, signatureBase64, publicKeyPEM string) bool {
	if publicKeyPEM == "" {
		return false
	}

	// Decode the base64 signature
	signature, err := base64.StdEncoding.DecodeString(signatureBase64)
	if err != nil {
		// Try URL-safe base64
		signature, err = base64.URLEncoding.DecodeString(signatureBase64)
		if err != nil {
			return false
		}
	}

	// Parse PEM public key
	block, _ := pem.Decode([]byte(publicKeyPEM))
	if block == nil || block.Type != "PUBLIC KEY" {
		return false
	}

	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return false
	}

	rsaPub, ok := pub.(*rsa.PublicKey)
	if !ok {
		return false
	}

	// Compute SHA-256 hash of the payload
	hashed := sha256.Sum256(payload)

	// Verify RSA PKCS#1 v1.5 signature
	err = rsa.VerifyPKCS1v15(rsaPub, crypto.SHA256, hashed[:], signature)
	return err == nil
}

// DefaultXHSVerifier is the default RSA verifier used by the XHS adapter.
func DefaultXHSVerifier(payload []byte, signature string, publicKeyPEM string) bool {
	return VerifyXHSRSA(payload, signature, publicKeyPEM)
}
