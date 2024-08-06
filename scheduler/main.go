package main

import (
	"os"

	"k8s.io/component-base/cli"
	_ "k8s.io/component-base/metrics/prometheus/clientgo" // for rest client metric registration
	_ "k8s.io/component-base/metrics/prometheus/version"  // for version metric registration
	"k8s.io/kubernetes/cmd/kube-scheduler/app"
	_ "sigs.k8s.io/scheduler-plugins/apis/config/scheme" // Ensure scheme package is initialized.

	"github.com/jimyag/k8sdev/scheduler/internal"
)

func main() {
	// Register custom plugins to the scheduler framework.
	// Later they can consist of scheduler profile(s) and hence
	// used by various kinds of workloads.
	command := app.NewSchedulerCommand(
		app.WithPlugin(internal.Name, internal.New),
	)

	code := cli.Run(command)
	os.Exit(code)
}
