# init-pod

## 作用

1. 下载主容器的依赖的工具、配置、缓存到共享的目录 一般都是 empty dir
2. 检查外部的依赖是否就绪，如果没有就绪就不启动
3. 初始化主容器需要的配置，比如 admission webhook 需要用到集群的 ca 证书。可以利用一个 init pod 自动生成 证书，并且挂载到主容器。

## 特点

1. 可以有多个 init container
2. 他们是顺序执行的，如果一个失败，后面的不会执行。
3. 他们和主容器要通过共享的目录来通信。
4. 共享 cpu memory 的 request 和 limit
