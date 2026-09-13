FROM golang:1.23-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
COPY extended-resource ./extended-resource
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o /out/device-plugin ./extended-resource

FROM alpine:3.20
COPY --from=build /out/device-plugin /device-plugin
USER 65532:65532
ENTRYPOINT ["/device-plugin"]
