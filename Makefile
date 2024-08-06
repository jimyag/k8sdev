
GOBIN=$(shell pwd)/bin
GOPATH=$(shell go env GOPATH | awk -F: '{print $$1}')

baseImageUrl?=registry.i.jimyag.com
baseImageTag?=$(shell TZ='Asia/Shanghai' date "+%Y-%m-%d-%H-%M-%S")


.PHONY: build tidy container-scheduler

build: tidy
	CGO_ENABLED=0 GOBIN=$(GOBIN) go install -trimpath -v ./...

tidy:
	go mod tidy

container-scheduler: build
	docker build -t $(baseImageUrl)/k8sdev/scheduler:$(baseImageTag) \
		--progress=plain --target scheduler --push --platform linux/amd64 \
		-f ./Dockerfile  .