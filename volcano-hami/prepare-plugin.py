#!/usr/bin/env python3
"""从固定上游清单生成 kind + mock 专用配置，保留上游许可证。"""
import json
import sys
from pathlib import Path
import yaml

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text()
license_text = text.split('---', 1)[0]
docs = list(yaml.safe_load_all(text))
for obj in docs:
    if obj['metadata']['name'] == 'volcano-vgpu-device-config':
        cfg = yaml.safe_load(obj['data']['device-config.yaml'])
        cfg['nvidia']['gpuMemoryFactor'] = 100
        obj['data']['device-config.yaml'] = '# 每个显存资源单位代表 100 MiB，避免 ListAndWatch 超过 gRPC 4 MiB。\n' + yaml.safe_dump(cfg, sort_keys=False)
    if obj['metadata']['name'] == 'volcano-vgpu-node-config':
        obj['data']['config.json'] = json.dumps({'nodeconfig': [
            {'name': n, 'operatingmode': 'hami-core', 'devicememoryscaling': 1,
             'devicesplitcount': 10, 'migstrategy': 'none'}
            for n in ['volcano-lab-worker', 'volcano-lab-worker2']
        ]}, indent=2)
    if obj['kind'] == 'DaemonSet':
        spec = obj['spec']['template']['spec']
        spec['runtimeClassName'] = 'nvidia'
        spec['nodeSelector'] = {'gpu': 'on'}
        for c in spec['containers']:
            c['image'] = 'projecthami/volcano-vgpu-device-plugin:v1.12.0'
            c['imagePullPolicy'] = 'IfNotPresent'
        spec['containers'][0]['args'] = ['--device-split-count=10', '--pass-device-specs=false', '--nvidia-driver-root=/run/nvidia/driver']
docs.insert(0, {'apiVersion': 'node.k8s.io/v1', 'kind': 'RuntimeClass', 'metadata': {'name': 'nvidia'}, 'handler': 'nvidia'})
target.write_text(license_text + '\n# 实验适配：CDI runtime 注入模拟设备；仅 GPU worker 部署插件。\n'
                  '# 共享名额为每卡 10 份，显存不超售；禁用额外 DeviceSpec，避免重复注入。\n'
                  '# 两个容器统一固定 v1.12.0，使用本地预加载镜像。\n'
                  + yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True))
