# 从文章固定提交复现实验

`article-*` 实验目录共用这里的版本准备步骤。先在 `zj` 上取得 k8sdev 的 Git 克隆，再从文章的实验链接中复制完整的 40 位提交号，设置 `ARTICLE_LABS_REV`。例如链接形如 `https://github.com/jimyag/k8sdev/tree/<40位提交号>/article-resources-memory`，应复制 `tree/` 后的提交号，不使用分支名、`HEAD` 或 Kubernetes 自身的提交号。

下面的代码块在 Bash 中执行。`ARTICLE_LABS_REV` 必须由文章中的固定链接提供；没有设置或格式错误时停止，避免悄悄使用当前分支的文件。已有 k8sdev 克隆可以直接使用；没有克隆时，先在自己选择的父目录执行 `git clone https://github.com/jimyag/k8sdev.git`，再进入该克隆。

```bash
set -euo pipefail
: "${ARTICLE_LABS_REV:?请先 export ARTICLE_LABS_REV=文章实验链接中的40位提交号}"
[[ "$ARTICLE_LABS_REV" =~ ^[0-9a-f]{40}$ ]] || { echo '需要完整的40位小写提交号' >&2; exit 1; }
export ARTICLE_REPO_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
git -C "$ARTICLE_REPO_ROOT" remote get-url origin
git -C "$ARTICLE_REPO_ROOT" fetch origin "$ARTICLE_LABS_REV"
test "$(git -C "$ARTICLE_REPO_ROOT" rev-parse "$ARTICLE_LABS_REV^{commit}")" = "$ARTICLE_LABS_REV"
export ARTICLE_ROOT="$ARTICLE_REPO_ROOT/.worktrees/article-labs-$ARTICLE_LABS_REV"
if [[ ! -e "$ARTICLE_ROOT" ]]; then
  git -C "$ARTICLE_REPO_ROOT" worktree add --detach "$ARTICLE_ROOT" "$ARTICLE_LABS_REV"
fi
test "$(git -C "$ARTICLE_ROOT" rev-parse --show-toplevel)" = "$ARTICLE_ROOT"
test "$(git -C "$ARTICLE_ROOT" rev-parse HEAD)" = "$ARTICLE_LABS_REV"
git -C "$ARTICLE_ROOT" diff --quiet HEAD -- . ':(exclude)article-*/evidence/**' ':(exclude)article-resources-*/results.json'
cd "$ARTICLE_ROOT"
mkdir -p tmp/article-reproduction
export TMPDIR="$ARTICLE_ROOT/tmp/article-reproduction"
git check-ignore -q tmp/article-reproduction/probe
printf '实验文件提交：%s\n实验根目录：%s\n' "$ARTICLE_LABS_REV" "$ARTICLE_ROOT"
```

这会在仓库根目录的 `.worktrees/` 下创建独立的 detached HEAD 工作目录，保留原工作区。已存在的目标目录只有在仓库根目录、HEAD 和实验输入文件均符合检查时才复用；检查失败时先确认目录归属和改动，不重置或覆盖它。检查只排除约定的运行结果目录 `article-*/evidence/` 和资源实验的 `results.json`，因为复跑会更新这些结果；脚本、清单、README 和其他已跟踪文件仍必须与提交一致。结果变化不能当成源码版本变化，也不能把新结果误当成原提交已经保存的历史证据。

在这个终端继续阅读目标实验 README。所有后续命令均使用 `$ARTICLE_ROOT`，工具、kubeconfig 和临时输出位于该工作目录的 `tmp/`。新开终端时，需要重新设置同一个 `ARTICLE_LABS_REV` 并执行上面的准备步骤。共享集群的多个主题应使用同一提交和同一工作目录，按各 README 的依赖顺序运行，不能在故障注入期间并发执行。

完成实验后先按各 README 清理自己创建的资源和 kind 集群，再移除凭据。需要保留的结果先放入主仓库的 `tmp/`；随后可以从主仓库运行 `git worktree remove "$ARTICLE_ROOT"`。有未保存改动或未跟踪产物时 Git 会拒绝移除，应逐项检查自己的产物，不使用强制删除，不清理其他实验的工作目录或集群。
