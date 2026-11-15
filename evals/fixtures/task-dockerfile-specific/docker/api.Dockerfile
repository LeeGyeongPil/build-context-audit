FROM golang:1.23 AS build
WORKDIR /src
COPY go.mod go.sum ./
COPY services/shared ./services/shared
COPY services/api ./services/api
COPY proto ./proto
RUN go build -o /api ./services/api
