package internal

import (
	"context"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/klog/v2"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

/*
	    +------------+
	     | PreEnqueue |
	     +------------+
	            |
	            V
	+------------------------+
	| --------> Sort         |
	+------------------------+
	            |
	            V
	+------------------------+
	|    Scheduling Cycle    |
	|------------------------|
	| -----> PreFilter       |
	| -----> Filter          |
	| -----> PostFilter      |
	| -----> PreScore        |
	| -----> Score           |
	| -----> NormalizeScore  |
	| + + +> Reserve         |
	|       Permit           |
	+------------------------+
	            |
	            V
	+------------------------+
	|     Binding Cycle      |
	|------------------------|
	| [    WaitOnPermit    ] |
	| -----> PreBind         |
	| -----> Bind            |
	| + + +> PostBind        |
	+------------------------+

Legend:
-----> Extension point (mutable)
+ + +> Extension point (informational)
[   ] Schedule framework internal API

  - Sort 扩展用于对 Pod 的待调度队列进行排序，以决定先调度哪个 Pod，
    Sort  扩展本质上只需要实现一个方法 Less(Pod1, Pod2) 用于比较两个 Pod 谁更优先获得调度即可，同一时间点只能有一个 QueueSort 插件生效。

mutable：
  - 影响调度结果
  - 所有的都成功了才是调度成功了

informational:
  - 不影响调度结果
  - 可以修改 pod 的信息
  - 执行清理操作
*/
const (
	// 插件名称
	Name = "JimyagCustom"
	// 插件状态存储的 key
	FilterLabel = "filter.k8sdev.jimyag.com"
)

var (
	_ framework.Plugin = &JimyagCustom{}
	// _ framework.PreFilterPlugin = &JimyagCustom{}
	_ framework.FilterPlugin = &JimyagCustom{}
	// _ framework.PostFilterPlugin = &JimyagCustom{}
	// _ framework.PreScorePlugin   = &JimyagCustom{}
	// _ framework.ScorePlugin      = &JimyagCustom{} // 包含 NormalizeScore
	//_ framework.ReservePlugin  = &JimyagCustom{}
	// _ framework.PermitPlugin   = &JimyagCustom{}
	// _ framework.PreBindPlugin  = &JimyagCustom{}
	// _ framework.BindPlugin     = &JimyagCustom{}
	// _ framework.PostBindPlugin = &JimyagCustom{}
)

type StateData struct {
	Msg string
}

func (s *StateData) Clone() framework.StateData {
	return s
}

// New 初始化一个插件并返回
func New(rawArgs runtime.Object, h framework.Handle) (framework.Plugin, error) {
	klog.Infof("New Scheduling plugin: %s", Name)
	// 拿到 kube config
	c := JimyagCustom{
		handle: h,
	}
	klog.Infof("%s plugin initialized", Name)
	return &c, nil
}

// JimyagCustom 是一个实现了所有扩展点 的示例插件
type JimyagCustom struct {
	handle framework.Handle
}

// Name 返回插件名称
func (c *JimyagCustom) Name() string {
	return Name
}

// PreFilter pod 预处理和检查，不符合预期就提前结束调度
// state 可用于保存一些状态信息，然后在后面的扩展点（例如 Filter() 阶段）拿出来用
// func (c *JimyagCustom) PreFilter(ctx context.Context, state *framework.CycleState, pod *v1.Pod) (*framework.PreFilterResult, *framework.Status) {
// 	klog.Infof("PreFilter %s/%s: start", pod.Namespace, pod.Name)
// 	// 做一些检查
// 	state.Write(StateKye, &StateData{
// 		Msg: "PreFilter set state",
// 	})
// 	klog.Infof("PreFilter %s/%s: finish", pod.Namespace, pod.Name)
// 	return nil, framework.NewStatus(framework.Success, "")
// }

// PreFilterExtensions returns preFilter extensions, pod add and remove.
// func (c *JimyagCustom) PreFilterExtensions() framework.PreFilterExtensions {
// 	return c
// }

// AddPod from pre-computed data in cycleState.
// no current need for this method.
// func (c *JimyagCustom) AddPod(ctx context.Context, cycleState *framework.CycleState, podToSchedule *v1.Pod, podToAdd *framework.PodInfo, nodeInfo *framework.NodeInfo) *framework.Status {
// 	klog.Infof("AddPod %s/%s: start", podToSchedule.Namespace, podToSchedule.Name)
// 	klog.Infof("AddPod %s/%s: nodeName: %s", podToSchedule.Namespace, podToSchedule.Name, nodeInfo.Node().Name)
// 	klog.Infof("AddPod %s/%s: finish", podToSchedule.Namespace, podToSchedule.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// RemovePod from pre-computed data in cycleState.
// no current need for this method.
// func (c *JimyagCustom) RemovePod(ctx context.Context, cycleState *framework.CycleState, podToSchedule *v1.Pod, podToRemove *framework.PodInfo, nodeInfo *framework.NodeInfo) *framework.Status {
// 	klog.Infof("RemovePod %s/%s: start", podToSchedule.Namespace, podToSchedule.Name)
// 	klog.Infof("RemovePod %s/%s: nodeName: %s", podToSchedule.Namespace, podToSchedule.Name, nodeInfo.Node().Name)
// 	klog.Infof("RemovePod %s/%s: finish", podToSchedule.Namespace, podToSchedule.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// Filter 过滤掉那些不满足要求的 node
// 过滤掉不包含
func (c *JimyagCustom) Filter(ctx context.Context, state *framework.CycleState, pod *v1.Pod, nodeInfo *framework.NodeInfo) *framework.Status {
	node := nodeInfo.Node()
	klog.Infof("Filter %s/%s/%s: start scheduler plugin", pod.Namespace, pod.Name, node.Name)
	podValue, found := pod.GetLabels()[FilterLabel]
	if !found {
		// 如果没有 pod 不包含  自定义的 filter，则可以任意分配
		klog.Infof("Filter %s/%s/%s: pod doesn't have '%s' label; can be scheduled",
			pod.Namespace, pod.Name, node.Name,
			FilterLabel)
		return framework.NewStatus(framework.Success, "")
	}
	nodeValue, found := node.GetLabels()[FilterLabel]
	if !found {
		// 如果 node 没有 自定义的 label，则不能被分配
		klog.Infof("Filter %s/%s/%s:  node doesn't have '%s' label; pod cannot be scheduled here",
			pod.Namespace, pod.Name, node.Name,
			FilterLabel)
		return framework.NewStatus(framework.Unschedulable, "node does not have required label")
	}
	if nodeValue != podValue {
		// 如果 pod 中 filter label 的值不等于 node 中 filter label 的值，则不能被分配
		klog.Infof("Filter %s/%s/%s: node '%s' label value %s does not match pod label value (%s)",
			pod.Namespace, pod.Name, node.Name,
			FilterLabel, nodeValue, podValue)
		return framework.NewStatus(framework.Unschedulable, "nodeGroup of pod and node don't match")
	}

	klog.Infof("Filter %s/%s/%s: finished, node '%s' : values match %s",
		pod.Namespace, pod.Name, node.Name,
		FilterLabel, nodeValue)
	// 拿到 state，进行下一步操作
	return framework.NewStatus(framework.Success, "")
}

// PostFilter 如果 Filter 阶段之后，所有 nodes 都被筛掉了，一个都没剩，才会执行这个阶段；否则不会执行这个阶段的 plugins。
// 按 plugin 顺序依次执行，任何一个插件将 node 标记为 Shedable 就算成功，不再执行剩下的 PostFilter plugins。
// func (c *JimyagCustom) PostFilter(ctx context.Context, state *framework.CycleState, pod *v1.Pod, filteredNodeStatusMap framework.NodeToStatusMap) (*framework.PostFilterResult, *framework.Status) {
// 	klog.Infof("PostFilter %s/%s: start", pod.Namespace, pod.Name)
// 	klog.Infof("PostFilter %s/%s: finish", pod.Namespace, pod.Name)
// 	return nil, framework.NewStatus(framework.Success, "")
// }

// func (c *JimyagCustom) PreScore(ctx context.Context, state *framework.CycleState, pod *v1.Pod, nodes []*v1.Node) *framework.Status {
// 	klog.Infof("PreScore %s/%s: start", pod.Namespace, pod.Name)
// 	klog.Infof("PreScore %s/%s: finish", pod.Namespace, pod.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// func (c *JimyagCustom) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
// 	klog.Infof("Score %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("Score %s/%s: finish", p.Namespace, p.Name)
// 	return 0, framework.NewStatus(framework.Success, "")
// }

// func (c *JimyagCustom) ScoreExtensions() framework.ScoreExtensions {
// 	return c
// }

// // NormalizeScore implements framework.ScoreExtensions.
// func (c *JimyagCustom) NormalizeScore(ctx context.Context, state *framework.CycleState, p *v1.Pod, scores framework.NodeScoreList) *framework.Status {
// 	klog.Infof("NormalizeScore %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("NormalizeScore %s/%s: finish", p.Namespace, p.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// func (c *JimyagCustom) Reserve(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) *framework.Status {
// 	klog.Infof("Reserve %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("Reserve %s/%s: finish", p.Namespace, p.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// func (c *JimyagCustom) Unreserve(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) {
// 	klog.Infof("Unreserve %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("Unreserve %s/%s: finish", p.Namespace, p.Name)
// }

// Permit approve：所有 Permit plugins 都 appove 之后，这个 pod 就进入下面的 binding 阶段；
// deny：任何一个 Permit plugin deny 之后，就无法进入 binding 阶段。这会触发 Reserve plugins 的 Unreserve() 方法；
// wait (with a timeout)：如果有 Permit plugin 返回“wait”，这个 pod 就会进入一个 internal“waiting”Pods list；
// func (c *JimyagCustom) Permit(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (*framework.Status, time.Duration) {
// 	klog.Infof("Permit %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("Permit %s/%s: finish", p.Namespace, p.Name)
// 	return framework.NewStatus(framework.Success, ""), 0
// }

// PreBind Bind 之前的预处理，例如到 node 上去挂载 volume
// func (c *JimyagCustom) PreBind(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) *framework.Status {
// 	klog.Infof("PreBind %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("PreBind %s/%s: finish", p.Namespace, p.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// Bind 绑定
// func (c *JimyagCustom) Bind(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) *framework.Status {
// 	klog.Infof("Bind %s/%s: start", p.Namespace, p.Name)
// 	klog.Infof("Bind %s/%s: finish", p.Namespace, p.Name)
// 	return framework.NewStatus(framework.Success, "")
// }

// PostBind 绑定之后的处理 这是一个 informational extension point，也就是无法影响调度决策（没有返回值）。
// bind 成功的 pod 才会进入这个阶段；
// 作为 binding cycle 的最后一个阶段，一般是用来清理一些相关资源。
// func (c *JimyagCustom) PostBind(ctx context.Context, state *framework.CycleState, pod *v1.Pod, nodeName string) {
// 	klog.Infof("PostBind %s/%s: start", pod.Namespace, pod.Name)
// 	klog.Infof("PostBind %s/%s: finish", pod.Namespace, pod.Name)
// }
