### Component / version

Mock NVML at `874ab0319732981bc79cbc9b01c22c8fd00656e6`, built from source.

### What happened

With two configured mock GPUs and only `/dev/nvidia1` present in the container:

```text
nvmlDeviceGetCount_v2()          -> 1
nvmlDeviceGetHandleByIndex_v2(0) -> SUCCESS, handle h
nvmlDeviceGetIndex(h)            -> 1
nvmlDeviceGetHandleByIndex_v2(1) -> NVML_ERROR_INVALID_ARGUMENT
```

### Expected behaviour

For a non-MIG device and an unchanged device set, the index returned by `GetIndex` should resolve back to the same handle through `GetHandleByIndex_v2`.

`GetHandleByIndex` maps through `visibleDevices`, while `GetIndex` returns the original `d.index`. Is preserving the original index intentional? How should these two APIs stay consistent? This report does not assume that a container's sole accessible GPU must always have NVML index 0.

### Steps to reproduce

Use the manifest below on a node with the mock library already installed. Adjust `nodeSelector` and `hostPath.path` and create the `hami-tests` namespace if needed. No HAMi, device plugin, real GPU, or privileged container is required.

The ConfigMap supplies an empty `/dev/nvidia1` file because the mock checks device presence using `os.Stat`.

<details>
<summary>nvml-index-repro.yaml</summary>

```yaml
# Requires a node with the mock NVML library already installed.
# Adjust nodeSelector and hostPath for your cluster.
apiVersion: v1
kind: ConfigMap
metadata:
  name: nvml-index-repro
  namespace: hami-tests
data:
  nvidia1: ""
---
apiVersion: v1
kind: Pod
metadata:
  name: nvml-index-repro
  namespace: hami-tests
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: hami-test-worker
  containers:
    - name: probe
      image: python:3.12-slim-bookworm
      env:
        - name: MOCK_NVML_NUM_DEVICES
          value: "2"
      command: [python3, -u, -c]
      args:
        - |
          import ctypes as C
          import sys

          lib = C.CDLL("/opt/mock/libnvidia-ml.so.1")
          def function(name, *args):
              fn = getattr(lib, name)
              fn.argtypes = list(args)
              fn.restype = C.c_int
              return fn

          uintp, handlep = C.POINTER(C.c_uint), C.POINTER(C.c_void_p)
          init = function("nvmlInit_v2")
          shutdown = function("nvmlShutdown")
          count = function("nvmlDeviceGetCount_v2", uintp)
          get = function("nvmlDeviceGetHandleByIndex_v2", C.c_uint, handlep)
          index = function("nvmlDeviceGetIndex", C.c_void_p, uintp)
          minor = function("nvmlDeviceGetMinorNumber", C.c_void_p, uintp)
          def check(ret):
              if ret != 0:
                  raise RuntimeError(f"NVML call failed: {ret}")

          check(init())
          try:
              n = C.c_uint()
              check(count(C.byref(n)))
              print(f"count={n.value}")
              if n.value != 1:
                  raise RuntimeError("Expected one visible device; check the mock configuration")
              h, back = C.c_void_p(), C.c_void_p()
              idx, physical_minor = C.c_uint(), C.c_uint()
              check(get(0, C.byref(h)))
              check(index(h, C.byref(idx)))
              check(minor(h, C.byref(physical_minor)))
              ret = get(idx.value, C.byref(back))
              same = ret == 0 and h.value == back.value
              print(f"enumerated=0 returned_index={idx.value} minor={physical_minor.value}")
              print(f"roundtrip_ret={ret} same_handle={int(same)}")
              passed = same and physical_minor.value == 1
              print("PASS" if passed else "FAIL: returned index does not resolve to the same device")
              sys.exit(0 if passed else 1)
          finally:
              check(shutdown())
      volumeMounts:
        - name: mock-library
          mountPath: /opt/mock/libnvidia-ml.so.1
          readOnly: true
        - name: visible-device
          mountPath: /dev/nvidia1
          subPath: nvidia1
          readOnly: true
  volumes:
    - name: mock-library
      hostPath:
        path: /var/lib/nvml-mock/driver/usr/lib64/libnvidia-ml.so.1
        type: File
    - name: visible-device
      configMap:
        name: nvml-index-repro
```

</details>

```sh
kubectl --context kind-hami-test apply -f nvml-index-repro.yaml
kubectl --context kind-hami-test -n hami-tests logs -f nvml-index-repro
# After collecting the output:
kubectl --context kind-hami-test delete -f nvml-index-repro.yaml
```

Replace the context name for your cluster. If logs report `ContainerCreating`, retry after startup.

### Environment

Linux/amd64, Ubuntu 24.04.4 LTS, kernel 6.8.0-138-generic; Kind 0.31.0, Kubernetes 1.35.0, containerd 2.2.0. CPU-only host, no physical NVIDIA GPU/driver. Probe image: `python:3.12-slim-bookworm`.

### Logs / artefacts

Original library, Pod exits with code 1:

```text
count=1
enumerated=0 returned_index=1 minor=1
roundtrip_ret=2 same_handle=0
FAIL: returned index does not resolve to the same device
```

I tested a candidate fix that maintains a separate visible NVML index while retaining physical device identity. With the same manifest and only the mounted library changed, the Pod exits with code 0:

```text
count=1
enumerated=0 returned_index=0 minor=1
roundtrip_ret=0 same_handle=1
PASS
```

The candidate also has Go regression coverage for unfiltered enumeration and visible sets `[0]`, `[1]`, `[1,3]`, and `[2,3]`. I have not compared it against real-driver container visibility behaviour.

**I can work on the fix and submit a PR once we agree on the intended indexing behaviour.**

### Pre-submission checks

- [x] I searched existing issues and Discussions and did not find a duplicate. Related #306 introduced visibility filtering.
- [x] This reports a reproducible API inconsistency, rather than a usage question.
