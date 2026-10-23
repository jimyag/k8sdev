#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ../tmp/article-tools ../tmp/article-control
tools=$(cd ../tmp/article-tools && pwd)
download=$(cd ../tmp/article-control && pwd)/kubectl.download
curl --fail --location --retry 2 https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl -o "$download"
curl --fail --location --retry 2 https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl.sha256 -o "$download.sha256"
test "$(sha256sum "$download" | cut -d ' ' -f 1)" = "$(cat "$download.sha256")"
chmod +x "$download"
mv "$download" "$tools/kubectl"
rm "$download.sha256"
"$tools/kubectl" version --client
"$HOME/.local/bin/kind" version
docker info --format '{{.ServerVersion}}'
