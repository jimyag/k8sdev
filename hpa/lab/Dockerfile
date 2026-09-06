# 用固定版本 Go 编译静态二进制，运行镜像不需要 Go 工具链。
FROM golang:1.26.5-bookworm AS build
WORKDIR /src
COPY main.go .
# 禁用 CGO，避免运行阶段依赖动态链接库。
RUN CGO_ENABLED=0 go build -o /demo main.go
# 运行阶段只包含程序，不携带构建工具和实验文件。
FROM scratch
COPY --from=build /demo /demo
# 使用非 root 用户运行；程序监听无需特权的 8080 端口。
USER 65532:65532
ENTRYPOINT ["/demo"]
