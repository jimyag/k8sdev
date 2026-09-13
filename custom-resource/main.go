package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	dynamicinformer "k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/workqueue"
)

var webAppGVR = schema.GroupVersionResource{
	Group:    "apps.demo.example.com",
	Version:  "v1",
	Resource: "webapps",
}

func main() {
	var kubeconfig string
	flag.StringVar(&kubeconfig, "kubeconfig", "", "path to a kubeconfig file when running outside a cluster")
	flag.Parse()

	config, err := kubeConfig(kubeconfig)
	if err != nil {
		log.Fatalf("build Kubernetes config: %v", err)
	}

	dynamicClient, err := dynamic.NewForConfig(config)
	if err != nil {
		log.Fatalf("create dynamic client: %v", err)
	}
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		log.Fatalf("create typed client: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dynamicFactory := dynamicinformer.NewDynamicSharedInformerFactory(dynamicClient, 0)
	c := newController(
		dynamicClient,
		clientset,
		dynamicFactory.ForResource(webAppGVR).Informer(),
	)

	dynamicFactory.Start(ctx.Done())
	if !cache.WaitForCacheSync(ctx.Done(), c.webApps.HasSynced) {
		log.Fatal("wait for informer caches")
	}

	log.Println("webapp controller started")
	c.run(ctx, 2)
}

func kubeConfig(kubeconfig string) (*rest.Config, error) {
	if kubeconfig == "" {
		if config, err := rest.InClusterConfig(); err == nil {
			return config, nil
		}
		kubeconfig = filepath.Join(os.Getenv("HOME"), ".kube", "config")
	}
	return clientcmd.BuildConfigFromFlags("", kubeconfig)
}

type controller struct {
	dynamicClient dynamic.Interface
	clientset     kubernetes.Interface
	webApps       cache.SharedIndexInformer
	queue         workqueue.RateLimitingInterface
}

func newController(
	dynamicClient dynamic.Interface,
	clientset kubernetes.Interface,
	webApps cache.SharedIndexInformer,
) *controller {
	c := &controller{
		dynamicClient: dynamicClient,
		clientset:     clientset,
		webApps:       webApps,
		queue:         workqueue.NewNamedRateLimitingQueue(workqueue.DefaultControllerRateLimiter(), "webapps"),
	}
	webApps.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    c.enqueue,
		UpdateFunc: func(_, newObj any) { c.enqueue(newObj) },
		DeleteFunc: c.enqueue,
	})
	return c
}

func (c *controller) enqueue(obj any) {
	key, err := cache.MetaNamespaceKeyFunc(obj)
	if err != nil {
		log.Printf("enqueue object: %v", err)
		return
	}
	c.queue.Add(key)
}

func (c *controller) run(ctx context.Context, workers int) {
	for range workers {
		go c.worker(ctx)
	}
	<-ctx.Done()
	c.queue.ShutDown()
}

func (c *controller) worker(ctx context.Context) {
	for c.processNextItem(ctx) {
	}
}

func (c *controller) processNextItem(ctx context.Context) bool {
	item, shutdown := c.queue.Get()
	if shutdown {
		return false
	}
	defer c.queue.Done(item)

	key, ok := item.(string)
	if !ok {
		c.queue.Forget(item)
		log.Printf("discard queue item with unexpected type %T", item)
		return true
	}

	poll, err := c.reconcile(ctx, key)
	if err != nil {
		log.Printf("reconcile %s: %v", key, err)
		c.queue.AddRateLimited(key)
		return true
	}
	c.queue.Forget(item)
	if poll {
		c.queue.AddAfter(key, 2*time.Second)
	}
	return true
}

func (c *controller) reconcile(ctx context.Context, key string) (bool, error) {
	obj, exists, err := c.webApps.GetIndexer().GetByKey(key)
	if err != nil {
		return false, err
	}
	if !exists {
		return false, nil
	}

	webApp, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return false, fmt.Errorf("unexpected WebApp object type %T", obj)
	}
	return c.reconcileWebApp(ctx, webApp.DeepCopy())
}
