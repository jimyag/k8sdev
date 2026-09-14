package main

import (
	"fmt"
	"slices"
	"sync"

	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

type resourceManager interface {
	Devices() []*pluginapi.Device
	HealthUpdates() <-chan struct{}
	UpdateHealth(deviceID, health string) error
	ValidateAllocation(request *pluginapi.AllocateRequest) error
	PreferredAllocation(request *pluginapi.ContainerPreferredAllocationRequest) ([]string, error)
}

type fakeResourceManager struct {
	mu      sync.RWMutex
	devices map[string]*pluginapi.Device
	order   []string
	updates chan struct{}
}

func newFakeResourceManager(deviceCount int) *fakeResourceManager {
	devices := make(map[string]*pluginapi.Device, deviceCount)
	order := make([]string, 0, deviceCount)
	for i := range deviceCount {
		device := &pluginapi.Device{
			ID:     fmt.Sprintf("fpga-%d", i),
			Health: pluginapi.Healthy,
		}
		devices[device.ID] = device
		order = append(order, device.ID)
	}
	return &fakeResourceManager{
		devices: devices,
		order:   order,
		updates: make(chan struct{}, 1),
	}
}

func (m *fakeResourceManager) Devices() []*pluginapi.Device {
	m.mu.RLock()
	defer m.mu.RUnlock()

	devices := make([]*pluginapi.Device, 0, len(m.order))
	for _, deviceID := range m.order {
		device := *m.devices[deviceID]
		devices = append(devices, &device)
	}
	return devices
}

func (m *fakeResourceManager) HealthUpdates() <-chan struct{} {
	return m.updates
}

func (m *fakeResourceManager) UpdateHealth(deviceID, health string) error {
	if health != pluginapi.Healthy && health != pluginapi.Unhealthy {
		return fmt.Errorf("unsupported health %q", health)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	device, ok := m.devices[deviceID]
	if !ok {
		return fmt.Errorf("unknown device ID %q", deviceID)
	}
	if device.Health == health {
		return nil
	}
	device.Health = health
	select {
	case m.updates <- struct{}{}:
	default:
	}
	return nil
}

func (m *fakeResourceManager) ValidateAllocation(request *pluginapi.AllocateRequest) error {
	m.mu.RLock()
	defer m.mu.RUnlock()

	requested := make(map[string]int)
	for containerIndex, containerRequest := range request.ContainerRequests {
		for _, deviceID := range containerRequest.DevicesIDs {
			device, ok := m.devices[deviceID]
			if !ok {
				return fmt.Errorf("unknown device ID %q", deviceID)
			}
			if device.Health != pluginapi.Healthy {
				return fmt.Errorf("device ID %q is %s", deviceID, device.Health)
			}
			if previousContainer, ok := requested[deviceID]; ok {
				return fmt.Errorf("device ID %q requested by containers %d and %d", deviceID, previousContainer, containerIndex)
			}
			requested[deviceID] = containerIndex
		}
	}
	return nil
}

func (m *fakeResourceManager) PreferredAllocation(request *pluginapi.ContainerPreferredAllocationRequest) ([]string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	available := make(map[string]struct{}, len(request.AvailableDeviceIDs))
	for _, deviceID := range request.AvailableDeviceIDs {
		device, ok := m.devices[deviceID]
		if !ok {
			return nil, fmt.Errorf("unknown available device ID %q", deviceID)
		}
		if device.Health != pluginapi.Healthy {
			return nil, fmt.Errorf("available device ID %q is %s", deviceID, device.Health)
		}
		available[deviceID] = struct{}{}
	}

	allocationSize := int(request.AllocationSize)
	selected := make([]string, 0, allocationSize)
	selectedSet := make(map[string]struct{}, allocationSize)
	for _, deviceID := range request.MustIncludeDeviceIDs {
		if _, ok := available[deviceID]; !ok {
			return nil, fmt.Errorf("must-include device ID %q is not available", deviceID)
		}
		if _, ok := selectedSet[deviceID]; ok {
			continue
		}
		selected = append(selected, deviceID)
		selectedSet[deviceID] = struct{}{}
	}
	if len(selected) > allocationSize {
		return nil, fmt.Errorf("must-include devices %d exceed allocation size %d", len(selected), allocationSize)
	}

	for _, deviceID := range request.AvailableDeviceIDs {
		if len(selected) == allocationSize {
			break
		}
		if _, ok := selectedSet[deviceID]; ok {
			continue
		}
		selected = append(selected, deviceID)
		selectedSet[deviceID] = struct{}{}
	}
	if len(selected) != allocationSize {
		return nil, fmt.Errorf("requested %d devices, only %d are available", allocationSize, len(available))
	}
	return slices.Clone(selected), nil
}
