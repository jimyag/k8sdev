#!/usr/bin/env bash

# 获取所有节点
nodes=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')

# 将节点列表转换为数组
nodes_array=( $nodes )

# 获取节点数量
num_nodes=${#nodes_array[@]}

# 检查是否有可用节点
if [ "$num_nodes" -eq 0 ]; then
  echo "No nodes found."
  exit 1
fi

# 随机选择一个节点
random_index=$((RANDOM % num_nodes))
random_node=${nodes_array[$random_index]}

# 标签键和值
label_key="scheduler.k8sdev.jimyag.com/filter"
label_value="normal"

# 给随机节点打标签
echo "Labeling node $random_node with $label_key=$label_value"

kubectl label node "$random_node" "$label_key=$label_value" --overwrite

label_key_others="filter"
label_value_others="normal"
for node in "${nodes_array[@]}"; do
  if [ "$node" != "$random_node" ]; then
    echo "Labeling node $node with $label_key_others=$label_value_others"
    kubectl label node "$node" "$label_key_others=$label_value_others" --overwrite
  fi
done