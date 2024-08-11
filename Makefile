
GOBIN=$(shell pwd)/bin
GOPATH=$(shell go env GOPATH | awk -F: '{print $$1}')

baseImageUrl?=registry.i.jimyag.com/
baseImageTag?=$(shell TZ='Asia/Shanghai' date "+%Y-%m-%d-%H-%M-%S")


.PHONY: build tidy container-scheduler



build: tidy
	CGO_ENABLED=0 go install -trimpath -v ./...

docker-base:
	@if [ "$(UNAME_S)" = "Linux" ] && [ "$(UNAME_M)" = "x86_64" ]; then \
		echo "Running target for AMD64 Linux"; \
		$(MAKE) build; \
	else \
		echo "Running target for non-AMD64 or non-Linux"; \
		$(MAKE) amd64_linux; \
	fi

amd64_linux:
	GOMODCACHE=$(GOPATH)/pkg/mod CGO_ENABLED=0 GOPATH=$(GOBIN) GOARCH=amd64 GOOS=linux go install -trimpath -v  ./...
	mkdir -p $(GOBIN)/linux_amd64
	mv -f $(GOBIN)/bin/linux_amd64/* $(GOBIN)/
	rm -rf $(GOBIN)/bin/ $(GOBIN)/linux_amd64

tidy:
	go mod tidy

container-scheduler: docker-base
	docker build -t $(baseImageUrl/k8sdev/scheduler:$(baseImageTag) \
		--progress=plain --target scheduler --push --platform linux/amd64 \
		-f ./Dockerfile  .