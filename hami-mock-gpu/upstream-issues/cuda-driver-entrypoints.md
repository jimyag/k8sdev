# Mock CUDA: missing Driver API entry points prevent CUDA 12.5 sample initialization

Issue draft; not submitted. This is a compatibility/support-scope report, with diagnostic patches rather than a complete CUDA execution implementation.

Tested `k8s-test-infra` at `874ab0319732981bc79cbc9b01c22c8fd00656e6` on Linux/amd64. The sample is `nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0`.

The built `libcuda.so.1` exports `cudaDriverGetVersion`, which reports 12080, but does not export `cuDriverGetVersion`, `cuGetProcAddress`, or `cuGetProcAddress_v2`. The CUDA sample fails even without HAMi or Kubernetes. With HAMi-core enabled, it fails earlier because the hook expects `cuGetProcAddress_v2`.

## Reproduction without HAMi or Kubernetes

Build the pinned revision using the builder-stage command in [the NVML report](nvml-visible-index.md). Set `REPRO` to the absolute directory containing the attached probes.

```sh
mkdir -p /tmp/mock-cuda-baseline
docker run --rm -v /tmp/mock-cuda-baseline:/out \
  hami-test/mock-builder:baseline sh -c \
  'cp -L /src/pkg/gpu/mockcuda/libcuda.so.1 /out/libcuda.so.1'

docker run --rm --runtime=runc -e MOCK_CUDA_DEBUG=1 \
  -v /tmp/mock-cuda-baseline/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
```

Actual result, exit status 1:

```text
Failed to allocate device vector A (error code CUDA driver version is insufficient for CUDA runtime version)!
[Vector addition of 50000 elements]
```

Inspect the ABI without a CUDA SDK:

```sh
docker run --rm -v "$REPRO:/repro:ro" hami-test/mock-builder:baseline sh -c '
  gcc /repro/cuda-symbol-probe.c -ldl -o /tmp/cuda-symbol-probe &&
  /tmp/cuda-symbol-probe /src/pkg/gpu/mockcuda/libcuda.so.1
'
```

Output includes:

```text
cuInit: present
cudaDriverGetVersion: present
cuDriverGetVersion: MISSING
cuGetProcAddress: MISSING
cuGetProcAddress_v2: MISSING
cuMemAlloc_v2: MISSING
cuLaunchKernel: MISSING
cudaDriverGetVersion: ret=0 version=12080
```

## Incremental changes and observed results

Two separate patches were tested:

1. [02-cuda-driver-version.patch](patches/02-cuda-driver-version.patch) exports `cuDriverGetVersion`, forwarding to the existing version implementation.
2. [03-cuda-entrypoints-experiment.patch](patches/03-cuda-entrypoints-experiment.patch) adds a deliberately narrow resolver for the implemented `cuInit`, `cuDriverGetVersion`, and the two resolver ABIs. It reports absent functions as absent. It does not substitute Runtime API functions for Driver API functions or emulate kernel execution.

| Library | Without HAMi hook | With HAMi hook |
|---|---|---|
| Original | Insufficient driver version | `cuGetProcAddress_v2 is NULL` |
| Version entry point only | `cuInit(0)` succeeds; sample reports unsupported API during allocation | Still `cuGetProcAddress_v2 is NULL` |
| Version + resolver | `cuInit(0)` succeeds; sample still reports unsupported API | Passes the resolver failure; reaches `cuDevicePrimaryCtxRetain is NULL` |

The standalone Docker sample and the Kubernetes control Pod show the same no-hook progression. All vectorAdd runs still fail. With the resolver patch and HAMi enabled, the Pod terminates with exit code 139 after the missing-context-entry message; without the hook it exits with code 1. These patches only move initialization past the first missing entries, and do not improve end-to-end reliability.

The resolver experiment logs requests for other unimplemented Driver APIs, including device discovery, primary contexts, memory allocation, and kernel launch. The existing `cudaLaunchKernel` implementation is a no-op; it cannot perform vector addition. Therefore, making the sample pass requires substantially more than exporting these three symbols.

The versioned resolver uses the CUDA 12+ rule that an unsupported symbol is reported through a null pointer and query status; the older resolver returns `CUDA_ERROR_NOT_FOUND`. See [CUDA 12.5 entry-point documentation](https://docs.nvidia.com/cuda/archive/12.5.1/cuda-driver-api/group__CUDA__DRIVER__ENTRY__POINT.html) and [CUDA 11.5 documentation](https://docs.nvidia.com/cuda/archive/11.5.2/cuda-driver-api/group__CUDA__DRIVER__ENTRY__POINT.html).

## Testing the experimental changes

In a clean checkout of the pinned revision:

```sh
git apply "$REPRO/patches/02-cuda-driver-version.patch"
# Build here first to test the version-only stage.
docker run --rm -v "$PWD:/work" -w /work \
  hami-test/mock-builder:baseline make -C pkg/gpu/mockcuda clean all
docker run --rm --runtime=runc -e MOCK_CUDA_DEBUG=1 \
  -v "$PWD/pkg/gpu/mockcuda/libcuda.so.550.163.01:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro" \
  nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0

git apply "$REPRO/patches/03-cuda-entrypoints-experiment.patch"
docker run --rm -v "$PWD:/work" -w /work \
  hami-test/mock-builder:baseline make -C pkg/gpu/mockcuda clean all
# Repeat the same Docker sample command for the resolver stage.

docker run --rm -v "$PWD:/work:ro" -v "$REPRO:/repro:ro" \
  hami-test/mock-builder:baseline sh -c '
    gcc /repro/cuda-entrypoints-test.c -ldl -o /tmp/cuda-entrypoints-test &&
    /tmp/cuda-entrypoints-test /work/pkg/gpu/mockcuda/libcuda.so.1
  '
```

The ABI test passes checks for version retrieval, initialization via the returned pointer, old/new resolver selection, missing symbols, insufficient requested versions, and invalid arguments. It is not a CUDA computation test.

## HAMi experiment details

HAMi v2.10.0, HAMi-core `b216ba1be1b8e21488d1c7370ed3357b3049aad1`; Kubernetes 1.35.0 / Kind 0.31.0; NVIDIA Container Toolkit 1.19.1-1 and CDI. Each comparison used a fresh Pod pinned to the same worker, requesting 4096 MiB and 25 cores. The mock CUDA library was explicitly mounted at `/usr/lib/x86_64-linux-gnu/libcuda.so.1`.

The control set `CUDA_DISABLE_CONTROL=true` to disable HAMi's preload injection. These runtime-injected mounts are not represented in the admitted Pod's `volumeMounts`. The NVML index candidate was present during both CUDA modification stages. It does not explain the standalone Docker reproductions, which load only the mock CUDA library.

## Suggested upstream scope

Could the project clarify which CUDA consumers the mock is intended to support, and whether the corresponding Driver API entry points should be provided for those consumers? Exporting `cuDriverGetVersion` is a small independent improvement. The resolver experiment helps identify the next missing APIs, but should not be presented as support for running arbitrary CUDA samples or testing GPU compute isolation.

Attachments:

- [Symbol probe](cuda-symbol-probe.c) and [baseline output](evidence/cuda-symbols-baseline.log).
- Standalone vectorAdd: [original](evidence/vectoradd-docker-baseline.log), [version only](evidence/vectoradd-docker-version.log), [resolver](evidence/vectoradd-docker-entrypoints.log).
- HAMi stage results: [version only](evidence/cuda-version-only-results.json), [resolver](evidence/cuda-entrypoints-results.json).
- [Pod termination states and exit codes](evidence/cuda-termination.json).
- [ABI test](cuda-entrypoints-test.c) and [passing output](evidence/cuda-entrypoints-test.log).
- [Full Go tests](evidence/make-test-nonroot.log), [lint/vet/vulnerability check](evidence/lint-fix.log).

The original libraries were restored after testing. No upstream issue or pull request has been submitted.
