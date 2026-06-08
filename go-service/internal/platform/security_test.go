package platform

import (
	"crypto"
	"crypto/hmac"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/pem"
	"testing"

	"github.com/stretchr/testify/assert"
)

// =============================================================================
// AES Encrypt/Decrypt roundtrip tests (WeComAdapter methods)
// =============================================================================

func TestEncryptDecrypt_Roundtrip(t *testing.T) {
	adapter := &WeComAdapter{}

	key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes
	plaintext := []byte("Hello, WeCom! This is a test message for AES-CBC.")

	ciphertext, err := adapter.aesEncrypt(plaintext, key)
	assert.NoError(t, err)
	assert.NotEmpty(t, ciphertext)

	// aesEncrypt returns base64-encoded ciphertext; decode before feeding to aesDecrypt
	rawCipher, err := base64.StdEncoding.DecodeString(ciphertext)
	assert.NoError(t, err)

	decrypted, err := adapter.aesDecrypt(rawCipher, key)
	assert.NoError(t, err)
	assert.Equal(t, string(plaintext), decrypted)
}

func TestDecrypt_InvalidCiphertext(t *testing.T) {
	adapter := &WeComAdapter{}

	key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes

	// Pass bytes that are valid AES block size but are garbage — will fail on PKCS7 unpadding
	garbage := make([]byte, 32) // 32 bytes, multiple of block size, all zeros
	_, err := adapter.aesDecrypt(garbage, key)
	assert.Error(t, err, "garbage ciphertext should fail on pkcs7 unpad")
}

func TestDecrypt_PanicsOnUnalignedInput(t *testing.T) {
	adapter := &WeComAdapter{}

	key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes

	// CryptBlocks panics if input is not a multiple of BlockSize (16).
	// Input > BlockSize but not aligned → panic
	assert.Panics(t, func() {
		adapter.aesDecrypt([]byte("not valid ciphertext at all"), key) // 27 bytes, not aligned
	}, "unaligned ciphertext should panic")
}

func TestDecrypt_EmptyCiphertext(t *testing.T) {
	adapter := &WeComAdapter{}

	key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes

	_, err := adapter.aesDecrypt([]byte{}, key)
	assert.Error(t, err)
}

func TestDecrypt_TooShortCiphertext(t *testing.T) {
	adapter := &WeComAdapter{}

	key := []byte("0123456789abcdef0123456789abcdef") // 32 bytes

	// Shorter than AES block size (16 bytes)
	_, err := adapter.aesDecrypt([]byte("short"), key)
	assert.Error(t, err)
}

// =============================================================================
// decodeAESKey tests (key validation)
// =============================================================================

func TestDecodeAESKey_Valid_32Bytes(t *testing.T) {
	adapter := &WeComAdapter{}

	// WeCom provides a 43-character base64 EncodingAESKey.
	// When decoded with base64 (with one '=' padding added by decodeAESKey), yields 32 bytes.
	// Create a 32-byte key, encode to base64, strip the trailing '=', giving a 43-char string.
	key32 := []byte("0123456789abcdef0123456789abcdef")
	encoded := base64.StdEncoding.EncodeToString(key32) // "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=" → 44 chars
	// decodeAESKey appends "=" so we strip one "="
	encoded43 := encoded[:len(encoded)-1] // 43 chars

	result, err := adapter.decodeAESKey(encoded43)
	assert.NoError(t, err)
	assert.Equal(t, 32, len(result))
	assert.Equal(t, key32, result)
}

func TestDecodeAESKey_InvalidLength(t *testing.T) {
	adapter := &WeComAdapter{}

	// 16-byte key encoded, giving a 43-char string that decodes to 16 bytes (not 32)
	key16 := []byte("0123456789abcdef")
	encoded := base64.StdEncoding.EncodeToString(key16) // "MDEyMzQ1Njc4OWFiY2RlZg==" → 24 chars
	// Strip one '=', decodeAESKey adds one back
	encoded23 := encoded[:len(encoded)-1]

	_, err := adapter.decodeAESKey(encoded23)
	assert.Error(t, err)

	// Also test with a 43-char string that decodes to 31 bytes
	key31 := []byte("0123456789abcdef0123456789abcde") // 31 bytes
	encoded31 := base64.StdEncoding.EncodeToString(key31) // has '=' padding
	encoded43_31 := encoded31[:len(encoded31)-1]         // strip so decodeAESKey adds it back

	_, err = adapter.decodeAESKey(encoded43_31)
	assert.Error(t, err)
}

// =============================================================================
// Douyin HMAC-SHA256 signature verification tests
// =============================================================================

func TestVerifyDouyinSignature_Roundtrip(t *testing.T) {
	appSecret := "douyin_secret_key_123"
	timestamp := "1620000000"
	nonce := "random_nonce_xyz"
	body := []byte(`{"msg_type":"text","content":"Hello"}`)

	// Compute expected signature
	mac := hmac.New(sha256.New, []byte(appSecret))
	mac.Write([]byte(appSecret))
	mac.Write([]byte(timestamp))
	mac.Write([]byte(nonce))
	mac.Write(body)
	expected := hex.EncodeToString(mac.Sum(nil))

	result := VerifyDouyinSignature(appSecret, timestamp, nonce, body, expected)
	assert.True(t, result, "valid Douyin signature should pass")
}

func TestVerifyDouyinSignature_WrongSecret(t *testing.T) {
	appSecret := "douyin_secret_key_123"
	timestamp := "1620000000"
	nonce := "random_nonce_xyz"
	body := []byte(`{"msg_type":"text","content":"Hello"}`)

	// Wrong signature
	result := VerifyDouyinSignature(appSecret, timestamp, nonce, body, "deadbeef")
	assert.False(t, result, "wrong signature should fail")
}

func TestVerifyDouyinSignature_DifferentBody(t *testing.T) {
	secret := "secret"
	ts := "1"
	nc := "2"
	body1 := []byte("a")
	body2 := []byte("b")

	sig1 := computeDouyinSig(secret, ts, nc, body1)
	sig2 := computeDouyinSig(secret, ts, nc, body2)

	assert.NotEqual(t, sig1, sig2, "different bodies should yield different signatures")
}

// =============================================================================
// XHS RSA signature verification tests
// =============================================================================

// Hardcoded RSA 2048-bit key pair for testing (test only — not a production key).
const testXHSPublicKeyPEM = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAr0IpAGD03qk8FGbPL344
42aMOXKDO6bzFjpQetzDbbcognxLxAHJuYOC4r/2YGcA99FXRiJV2sYYvfXd0cX6
crkoHWCYUNbdTTAAWpUeYvNogTED6anZyY7GVYjnIJ2Ly9UZVMvn5JUCWk/Semhp
IS0SRZa0KrFeGATM/09lGQejp5GnaWTamCgVY3ZHTEXlmNrZIuMhdTTeL7Y7Y8hP
h4rKZdn2/98NGrAjKEDNoglUW5NxGgz17ID2VlsOSUB8FuVAE2lW3EW0jnGxAolj
SzkfkLNdulwn/YLZYKUdRt5lb9LPKm9/hGtkFBTGj+DclOK2Ci/9JKGecivoENiI
3wIDAQAB
-----END PUBLIC KEY-----`

// testXHSPrivateKeyPEM is the matching private key for testXHSPublicKeyPEM.
const testXHSPrivateKeyPEM = `-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAr0IpAGD03qk8FGbPL34442aMOXKDO6bzFjpQetzDbbcognxL
xAHJuYOC4r/2YGcA99FXRiJV2sYYvfXd0cX6crkoHWCYUNbdTTAAWpUeYvNogTED
6anZyY7GVYjnIJ2Ly9UZVMvn5JUCWk/SemhpIS0SRZa0KrFeGATM/09lGQejp5Gn
aWTamCgVY3ZHTEXlmNrZIuMhdTTeL7Y7Y8hPh4rKZdn2/98NGrAjKEDNoglUW5Nx
Ggz17ID2VlsOSUB8FuVAE2lW3EW0jnGxAoljSzkfkLNdulwn/YLZYKUdRt5lb9LP
Km9/hGtkFBTGj+DclOK2Ci/9JKGecivoENiI3wIDAQABAoIBAAV1tdn0K0y7JaBW
akKcLQuF3f0gKyRy7q8U6/2X3mK5n60eUCyasv0biA/7qPeXMzmFL7HYpKdnH82I
g6Y4WQq1PUxaU68ZB9XoFpVmgIbWob0nQ2xGb/7Oetvz+DdU5nkCz4I2bqf5WGnA
g4RwDO5iqBIQ6tX1ppfFoS6cUOr2+7PMW6HJRYQSBcfhS8T3B0dx6YKZN4Vpgk1b
ebIyQ6kI5p+O4zrTNYdxxEqWm7+u6k2iSn9mrmgxbu62Mv258D9dw3C7YvZsvXa8
1uccPWK9NTBlaNO2Xh0cxdQzJj/UppSRA9cgtI0hUfUjzYDU/dsByjNJE8LfnuzP
PIgX4lECgYEA6RhhiRrHjIGuwocRS4Z8De7x75dcsip/uMxzIEDwQTE9upLC9xxX
alVDdkucyVHFyyaBjp8463RkVkLqe3E0S6OBHt/fjDlr/qUmQLmnvYWNd7FU/0o1
5kblLhNq9IQqA6BGAyxIU6l+/+G38bKpT2Ly9e9+e5+EYbsfJmsnmecCgYEAwHre
GkbPjDIIk7LW9o6kp79+jBvhc4SXVu7DVEU/Oe8+2i9E9boDZBQ26sJHsG8xcKVi
c2IQCscK41ljvNuxVAXNBRgZm5j7aX2BvBvZb2X3kO83w2bYqdmyaEOzT6IdyBmU
Wko8nG6lc+Vnk3Uf+d1YIXABf1pPH/00dioMakkCgYEA5pvuczyBS+tJQL9sRvJI
bWiHB2kSllohfm0XQUO97mGPFrT4Go55lYPBeJmaBjrWmwP/jWDNaXT/h7AwV+xJ
tsOOjUMj4ZE13Pr6+3IyF/i3W0GgO+nppWdiedFQMZVIE8pPOfhnng3Ezdc8quz9
QMM+aD6HPjs1N5NvYA0HYuUCgYEAmUuBxkWtGIfkotUlNPqIEn2FqMqvtNPdwEOq
V1xLLbXoRdatwlKiTrt2vWN7uv3jz0Y4cZKhGiRJ/KV9tLT3tuZj0XHPO0gMu4hU
od9APeNk1w5eSAaJ+kRCPZ3lmj+QHoSYzYwgV6obpYEIC72VeOebQA43cxkWuXBs
rstwVdkCgYA4FZCP5bNucXxaommEKOTjSQowVaZhhG6Jp8WJlF1kws970t2CPvuc
Rt4s8YQX26pQlfZD9DdJLnSLHeEJWg2KyuW78W/jIJ5FcKDZQwPGmc0X6v0HzwJz
wgI0x44Cs6anY4ESeMiTIb4dJiro/anJFSqesTj/PIucXKeHJNP98A==
-----END RSA PRIVATE KEY-----`

func TestVerifyXHSRSA_ValidSignature(t *testing.T) {
	payload := []byte("test_xhs_payload_12345")

	// Sign with private key using SHA-256 + PKCS1v15
	signature, err := signRSASHA256([]byte(testXHSPrivateKeyPEM), payload)
	assert.NoError(t, err)
	assert.NotEmpty(t, signature)

	// Verify with public key
	result := VerifyXHSRSA(payload, signature, testXHSPublicKeyPEM)
	assert.True(t, result, "valid RSA signature should pass")
}

func TestVerifyXHSRSA_WrongPayload(t *testing.T) {
	payload := []byte("test_xhs_payload_12345")
	wrongPayload := []byte("different_payload")

	signature, err := signRSASHA256([]byte(testXHSPrivateKeyPEM), payload)
	assert.NoError(t, err)

	// Verify with wrong payload
	result := VerifyXHSRSA(wrongPayload, signature, testXHSPublicKeyPEM)
	assert.False(t, result, "wrong payload should fail")
}

func TestVerifyXHSRSA_EmptyPublicKey(t *testing.T) {
	result := VerifyXHSRSA([]byte("data"), "signature", "")
	assert.False(t, result, "empty public key should return false")
}

func TestVerifyXHSRSA_InvalidSignatureBase64(t *testing.T) {
	result := VerifyXHSRSA([]byte("data"), "!!!not-valid-base64!!!", testXHSPublicKeyPEM)
	assert.False(t, result, "invalid base64 signature should return false")
}

func TestDefaultXHSVerifier(t *testing.T) {
	payload := []byte("verify_with_default")

	signature, err := signRSASHA256([]byte(testXHSPrivateKeyPEM), payload)
	assert.NoError(t, err)

	result := DefaultXHSVerifier(payload, signature, testXHSPublicKeyPEM)
	assert.True(t, result, "DefaultXHSVerifier should verify valid signatures")
}

// =============================================================================
// helpers
// =============================================================================

// computeDouyinSig is a helper to produce the expected Douyin HMAC-SHA256 signature.
func computeDouyinSig(appSecret, timestamp, nonce string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(appSecret))
	mac.Write([]byte(appSecret))
	mac.Write([]byte(timestamp))
	mac.Write([]byte(nonce))
	mac.Write(body)
	return hex.EncodeToString(mac.Sum(nil))
}

// signRSASHA256 signs a payload with RSA PKCS#1 v1.5 + SHA-256 using the given private key PEM.
// Returns a base64-encoded signature string.
func signRSASHA256(privateKeyPEM, payload []byte) (string, error) {
	block, _ := pem.Decode(privateKeyPEM)
	priv, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		return "", err
	}
	hashed := sha256.Sum256(payload)
	sig, err := rsa.SignPKCS1v15(rand.Reader, priv, crypto.SHA256, hashed[:])
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(sig), nil
}
