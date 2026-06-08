package model

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestHTTPStatus(t *testing.T) {
	tests := []struct {
		name     string
		code     int
		expected int
	}{
		{"CodeSuccess → 200", CodeSuccess, 200},
		{"CodeBadRequest → 400", CodeBadRequest, 400},
		{"CodeVerifyCodeErr → 400", CodeVerifyCodeErr, 400},
		{"CodeAlreadyExists → 400", CodeAlreadyExists, 400},
		{"CodeUnauthorized → 401", CodeUnauthorized, 401},
		{"CodeAPIKeyInvalid → 401", CodeAPIKeyInvalid, 401},
		{"CodeForbidden → 403", CodeForbidden, 403},
		{"CodeTenantInactive → 403", CodeTenantInactive, 403},
		{"CodeNotFound → 404", CodeNotFound, 404},
		{"CodeRateLimited → 429", CodeRateLimited, 429},
		{"CodeInternalError → 500", CodeInternalError, 500},
		{"CodePythonDown → 502", CodePythonDown, 502},
		{"CodeFEDown → 502", CodeFEDown, 502},
		{"CodeAgentTimeout → 504", CodeAgentTimeout, 504},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, HTTPStatus(tt.code))
		})
	}
}

func TestHTTPStatus_UnknownCode(t *testing.T) {
	tests := []struct {
		name     string
		code     int
		expected int
	}{
		{"high unknown code → 500", 9999, 500},
		{"negative code → 500", -1, 500},
		{"arbitrary unmapped code → 500", 7000, 500},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, HTTPStatus(tt.code))
		})
	}
}
