package model

const (
	CodeSuccess        = 0
	CodeBadRequest     = 4001
	CodeVerifyCodeErr  = 4002
	CodeAlreadyExists  = 4003
	CodeUnauthorized   = 4011
	CodeAPIKeyInvalid  = 4012
	CodeForbidden      = 4031
	CodeTenantInactive = 4032
	CodeNotFound       = 4041
	CodeRateLimited    = 4291
	CodeInternalError  = 5001
	CodePythonDown     = 5002
	CodeFEDown         = 5003
	CodeAgentTimeout   = 5041
)

var codeToHTTP = map[int]int{
	CodeSuccess:        200,
	CodeBadRequest:     400,
	CodeVerifyCodeErr:  400,
	CodeAlreadyExists:  400,
	CodeUnauthorized:   401,
	CodeAPIKeyInvalid:  401,
	CodeForbidden:      403,
	CodeTenantInactive: 403,
	CodeNotFound:       404,
	CodeRateLimited:    429,
	CodeInternalError:  500,
	CodePythonDown:     502,
	CodeFEDown:         502,
	CodeAgentTimeout:   504,
}

func HTTPStatus(code int) int {
	if s, ok := codeToHTTP[code]; ok {
		return s
	}
	return 500
}
