package main

import (
	"testing"

	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

func TestNewDevicePluginAdvertisesHealthyDevices(t *testing.T) {
	plugin := newDevicePlugin("example.com/fpga", 2)
	if len(plugin.devices) != 2 {
		t.Fatalf("device count = %d, want 2", len(plugin.devices))
	}
	for i, device := range plugin.devices {
		if device.ID != "fpga-"+string(rune('0'+i)) || device.Health != pluginapi.Healthy {
			t.Fatalf("device[%d] = %#v, want healthy fpga device", i, device)
		}
	}
}
