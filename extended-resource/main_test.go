package main

import (
	"context"
	"fmt"
	"sync"
	"testing"

	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

func TestNewDevicePluginAdvertisesHealthyDevices(t *testing.T) {
	plugin := newDevicePlugin("example.com/fpga", 2)
	if len(plugin.devices) != 2 {
		t.Fatalf("device count = %d, want 2", len(plugin.devices))
	}
	for i, device := range plugin.devices {
		if device.ID != fmt.Sprintf("fpga-%d", i) || device.Health != pluginapi.Healthy {
			t.Fatalf("device[%d] = %#v, want healthy fpga device", i, device)
		}
	}
}

func TestAllocateRejectsDuplicateDeviceIDs(t *testing.T) {
	plugin := newDevicePlugin("example.com/fpga", 2)
	_, err := plugin.Allocate(context.Background(), &pluginapi.AllocateRequest{
		ContainerRequests: []*pluginapi.ContainerAllocateRequest{
			{DevicesIDs: []string{"fpga-0"}},
			{DevicesIDs: []string{"fpga-0"}},
		},
	})
	if err == nil {
		t.Fatal("Allocate() error = nil, want duplicate device ID error")
	}
}

func TestAllocateHandlesConcurrentRequests(t *testing.T) {
	plugin := newDevicePlugin("example.com/fpga", 2)
	deviceIDs := []string{"fpga-0", "fpga-1"}

	var wg sync.WaitGroup
	errs := make(chan error, len(deviceIDs))
	for _, deviceID := range deviceIDs {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := plugin.Allocate(context.Background(), &pluginapi.AllocateRequest{
				ContainerRequests: []*pluginapi.ContainerAllocateRequest{
					{DevicesIDs: []string{deviceID}},
				},
			})
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)

	for err := range errs {
		if err != nil {
			t.Fatalf("concurrent Allocate() error = %v", err)
		}
	}
}
