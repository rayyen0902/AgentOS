# Stage 1: Build
FROM golang:1.22-alpine AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN GOPROXY=https://goproxy.cn,direct go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /server ./cmd/server/

# Stage 2: Run
FROM alpine:3.19

RUN apk add --no-cache ca-certificates

COPY --from=builder /server /server

EXPOSE 8080

ENTRYPOINT ["/server"]
