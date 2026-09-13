package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

const (
	pluginDir     = "/var/lib/kubelet/device-plugins"
	kubeletSocket = pluginDir + "/kubelet.sock"
)

type devicePlugin struct {
	resourceName string
	devices      []*pluginapi.Device
}

func main() {
	var resourceName string
	var deviceCount int
	flag.StringVar(&resourceName, "resource-name", "example.com/fpga", "extended resource name")
	flag.IntVar(&deviceCount, "device-count", 2, "number of healthy fake devices to advertise")
	flag.Parse()
	if deviceCount < 1 {
		log.Fatal("device-count must be positive")
	}

	plugin := newDevicePlugin(resourceName, deviceCount)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := plugin.run(ctx); err != nil {
		log.Fatal(err)
	}
}

func newDevicePlugin(resourceName string, deviceCount int) *devicePlugin {
	devices := make([]*pluginapi.Device, 0, deviceCount)
	for i := range deviceCount {
		devices = append(devices, &pluginapi.Device{
			ID:     fmt.Sprintf("fpga-%d", i),
			Health: pluginapi.Healthy,
		})
	}
	return &devicePlugin{resourceName: resourceName, devices: devices}
}

func (p *devicePlugin) run(ctx context.Context) error {
	socket := filepath.Join(pluginDir, "fpga.sock")
	if err := removeSocket(socket); err != nil {
		return err
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", socket, err)
	}
	defer listener.Close()

	server := grpc.NewServer()
	pluginapi.RegisterDevicePluginServer(server, p)
	serveErr := make(chan error, 1)
	go func() { serveErr <- server.Serve(listener) }()

	if err := register(ctx, socket, p.resourceName); err != nil {
		server.Stop()
		return err
	}
	log.Printf("registered %s with %d devices", p.resourceName, len(p.devices))

	select {
	case <-ctx.Done():
		server.GracefulStop()
		return nil
	case err := <-serveErr:
		return fmt.Errorf("device plugin server: %w", err)
	}
}

func removeSocket(path string) error {
	err := os.Remove(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove old socket: %w", err)
	}
	return nil
}

func register(ctx context.Context, socket, resourceName string) error {
	registerCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	conn, err := grpc.DialContext(registerCtx, kubeletSocket,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(ctx context.Context, address string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", address)
		}),
	)
	if err != nil {
		return fmt.Errorf("connect to kubelet registration socket: %w", err)
	}
	defer conn.Close()
	_, err = pluginapi.NewRegistrationClient(conn).Register(registerCtx, &pluginapi.RegisterRequest{
		Version:      pluginapi.Version,
		Endpoint:     filepath.Base(socket),
		ResourceName: resourceName,
		Options:      &pluginapi.DevicePluginOptions{},
	})
	if err != nil {
		return fmt.Errorf("register device plugin: %w", err)
	}
	return nil
}

func (p *devicePlugin) GetDevicePluginOptions(context.Context, *pluginapi.Empty) (*pluginapi.DevicePluginOptions, error) {
	return &pluginapi.DevicePluginOptions{}, nil
}

func (p *devicePlugin) ListAndWatch(_ *pluginapi.Empty, stream pluginapi.DevicePlugin_ListAndWatchServer) error {
	if err := stream.Send(&pluginapi.ListAndWatchResponse{Devices: p.devices}); err != nil {
		return err
	}
	<-stream.Context().Done()
	return nil
}

func (p *devicePlugin) GetPreferredAllocation(_ context.Context, request *pluginapi.PreferredAllocationRequest) (*pluginapi.PreferredAllocationResponse, error) {
	response := &pluginapi.PreferredAllocationResponse{ContainerResponses: make([]*pluginapi.ContainerPreferredAllocationResponse, 0, len(request.ContainerRequests))}
	for _, containerRequest := range request.ContainerRequests {
		if int(containerRequest.AllocationSize) > len(containerRequest.AvailableDeviceIDs) {
			return nil, fmt.Errorf("requested %d devices, only %d are available", containerRequest.AllocationSize, len(containerRequest.AvailableDeviceIDs))
		}
		response.ContainerResponses = append(response.ContainerResponses, &pluginapi.ContainerPreferredAllocationResponse{
			DeviceIDs: slices.Clone(containerRequest.AvailableDeviceIDs[:containerRequest.AllocationSize]),
		})
	}
	return response, nil
}

func (p *devicePlugin) Allocate(_ context.Context, request *pluginapi.AllocateRequest) (*pluginapi.AllocateResponse, error) {
	known := make(map[string]struct{}, len(p.devices))
	for _, device := range p.devices {
		known[device.ID] = struct{}{}
	}
	response := &pluginapi.AllocateResponse{ContainerResponses: make([]*pluginapi.ContainerAllocateResponse, 0, len(request.ContainerRequests))}
	for _, containerRequest := range request.ContainerRequests {
		for _, deviceID := range containerRequest.DevicesIDs {
			if _, ok := known[deviceID]; !ok {
				return nil, fmt.Errorf("unknown device ID %q", deviceID)
			}
		}
		response.ContainerResponses = append(response.ContainerResponses, &pluginapi.ContainerAllocateResponse{
			Envs: map[string]string{"DEMO_DEVICE_IDS": strings.Join(containerRequest.DevicesIDs, ",")},
		})
	}
	return response, nil
}

func (p *devicePlugin) PreStartContainer(context.Context, *pluginapi.PreStartContainerRequest) (*pluginapi.PreStartContainerResponse, error) {
	return &pluginapi.PreStartContainerResponse{}, nil
}
