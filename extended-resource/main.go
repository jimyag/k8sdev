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
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/fsnotify/fsnotify"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

const (
	pluginDir     = "/var/lib/kubelet/device-plugins"
	kubeletSocket = pluginDir + "/kubelet.sock"
)

var errKubeletRestart = errors.New("kubelet socket was removed")

type devicePlugin struct {
	resourceName string
	socket       string
	manager      resourceManager
	// Kubelet selects device IDs. This lock only serializes plugin-side
	// preparation that may be added to Allocate later.
	allocateMu sync.Mutex
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
	return &devicePlugin{
		resourceName: resourceName,
		socket:       pluginSocket(resourceName),
		manager:      newFakeResourceManager(deviceCount),
	}
}

func (p *devicePlugin) run(ctx context.Context) error {
	for {
		err := p.serve(ctx)
		if ctx.Err() != nil {
			return nil
		}
		if errors.Is(err, errKubeletRestart) {
			log.Printf("kubelet socket removed, re-registering %s", p.resourceName)
			continue
		}
		return err
	}
}

func (p *devicePlugin) serve(ctx context.Context) error {
	if err := removeSocket(p.socket); err != nil {
		return err
	}
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("create device plugin watcher: %w", err)
	}
	defer watcher.Close()
	if err := watcher.Add(pluginDir); err != nil {
		return fmt.Errorf("watch device plugin directory: %w", err)
	}

	listener, err := net.Listen("unix", p.socket)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", p.socket, err)
	}
	defer listener.Close()

	server := grpc.NewServer()
	pluginapi.RegisterDevicePluginServer(server, p)
	serveErr := make(chan error, 1)
	go func() { serveErr <- server.Serve(listener) }()

	if err := registerWithRetry(ctx, p.socket, p.resourceName); err != nil {
		server.Stop()
		return err
	}
	log.Printf("registered %s with %d devices", p.resourceName, len(p.manager.Devices()))

	for {
		select {
		case <-ctx.Done():
			server.GracefulStop()
			return nil
		case err := <-serveErr:
			if err != nil {
				return fmt.Errorf("device plugin server: %w", err)
			}
			return nil
		case event, ok := <-watcher.Events:
			if !ok {
				return errors.New("device plugin watcher events closed")
			}
			if event.Name == p.socket && event.Op&(fsnotify.Remove|fsnotify.Rename) != 0 {
				server.Stop()
				return errKubeletRestart
			}
		case err, ok := <-watcher.Errors:
			if !ok {
				return errors.New("device plugin watcher errors closed")
			}
			return fmt.Errorf("device plugin watcher: %w", err)
		}
	}
}

func removeSocket(path string) error {
	err := os.Remove(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove old socket: %w", err)
	}
	return nil
}

func registerWithRetry(ctx context.Context, socket, resourceName string) error {
	for {
		err := register(ctx, socket, resourceName)
		if err == nil {
			return nil
		}
		log.Printf("register %s failed: %v; retrying", resourceName, err)
		timer := time.NewTimer(time.Second)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
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
	return &pluginapi.DevicePluginOptions{GetPreferredAllocationAvailable: true}, nil
}

func (p *devicePlugin) ListAndWatch(_ *pluginapi.Empty, stream pluginapi.DevicePlugin_ListAndWatchServer) error {
	if err := stream.Send(&pluginapi.ListAndWatchResponse{Devices: p.manager.Devices()}); err != nil {
		return err
	}
	for {
		select {
		case <-p.manager.HealthUpdates():
			if err := stream.Send(&pluginapi.ListAndWatchResponse{Devices: p.manager.Devices()}); err != nil {
				return err
			}
		case <-stream.Context().Done():
			return nil
		}
	}
}

func (p *devicePlugin) GetPreferredAllocation(_ context.Context, request *pluginapi.PreferredAllocationRequest) (*pluginapi.PreferredAllocationResponse, error) {
	response := &pluginapi.PreferredAllocationResponse{ContainerResponses: make([]*pluginapi.ContainerPreferredAllocationResponse, 0, len(request.ContainerRequests))}
	for _, containerRequest := range request.ContainerRequests {
		deviceIDs, err := p.manager.PreferredAllocation(containerRequest)
		if err != nil {
			return nil, err
		}
		response.ContainerResponses = append(response.ContainerResponses, &pluginapi.ContainerPreferredAllocationResponse{
			DeviceIDs: deviceIDs,
		})
	}
	return response, nil
}

func (p *devicePlugin) Allocate(_ context.Context, request *pluginapi.AllocateRequest) (*pluginapi.AllocateResponse, error) {
	p.allocateMu.Lock()
	defer p.allocateMu.Unlock()

	if err := p.manager.ValidateAllocation(request); err != nil {
		return nil, err
	}
	response := &pluginapi.AllocateResponse{ContainerResponses: make([]*pluginapi.ContainerAllocateResponse, 0, len(request.ContainerRequests))}
	for _, containerRequest := range request.ContainerRequests {
		response.ContainerResponses = append(response.ContainerResponses, &pluginapi.ContainerAllocateResponse{
			Envs: map[string]string{"DEMO_DEVICE_IDS": strings.Join(containerRequest.DevicesIDs, ",")},
		})
	}
	return response, nil
}

func (p *devicePlugin) PreStartContainer(context.Context, *pluginapi.PreStartContainerRequest) (*pluginapi.PreStartContainerResponse, error) {
	return &pluginapi.PreStartContainerResponse{}, nil
}

func pluginSocket(resourceName string) string {
	return filepath.Join(pluginDir, strings.ReplaceAll(resourceName, "/", "-")+".sock")
}
