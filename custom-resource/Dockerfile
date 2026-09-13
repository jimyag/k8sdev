FROM golang:1.23-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY custom-resource ./custom-resource
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o /out/webapp-controller ./custom-resource

FROM alpine:3.20
COPY --from=build /out/webapp-controller /webapp-controller
USER 65532:65532
ENTRYPOINT ["/webapp-controller"]
