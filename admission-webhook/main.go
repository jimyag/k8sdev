package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"reflect"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mattbaird/jsonpatch"
	"gopkg.in/yaml.v3"
	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

type Config struct {
	Address string `yaml:"address"`
	TLS     struct {
		CertFile string `yaml:"certFile"`
		KeyFile  string `yaml:"keyFile"`
	} `yaml:"tls"`
}

func loadConfig() (Config, error) {
	if len(os.Args) < 2 {
		panic("missing config file path, ./admission-webhook config.yaml")
	}
	filename := os.Args[1]
	file, err := os.Open(filename)
	if err != nil {
		return Config{}, err
	}
	defer file.Close()
	cfg := Config{}
	if err = yaml.NewDecoder(file).Decode(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

type Service struct {
	cli      *kubernetes.Clientset
	nodeList *corev1.NodeList
	rwMut    sync.RWMutex
	cache    sync.Map
	next     int
}

func (p *Service) reload() error {
	nodes, err := p.cli.CoreV1().Nodes().List(context.Background(), metav1.ListOptions{})
	if err != nil {
		slog.Error("list nodes failed", "err", err)
		return err
	}
	sort.Slice(nodes.Items, func(i, j int) bool {
		return nodes.Items[i].Name < nodes.Items[j].Name
	})
	p.rwMut.Lock()
	defer p.rwMut.Unlock()
	p.nodeList = nodes
	return nil
}

func (p *Service) Next() corev1.Node {
	p.rwMut.Lock()
	defer p.rwMut.Unlock()
	p.next = (p.next + 1) % len(p.nodeList.Items)
	return p.nodeList.Items[p.next]
}

func (p *Service) backgroundReload() {
	ticker := time.NewTicker(time.Minute * 1)
	defer ticker.Stop()
	for range ticker.C {
		if err := p.reload(); err != nil {
			slog.Error("reload nodes failed", "err", err)
			continue
		}
	}
}

func NewService() (*Service, error) {
	p := &Service{
		rwMut: sync.RWMutex{},
		cache: sync.Map{},
	}
	config, err := rest.InClusterConfig()
	if err != nil {
		return nil, err
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, err
	}
	p.cli = clientset
	if err = p.reload(); err != nil {
		return nil, err
	}
	go p.backgroundReload()
	return p, nil
}

func (p *Service) Mutate(req *admissionv1.AdmissionRequest) (mutatedData []byte, mutate bool, err error) {
	pod := &corev1.Pod{}
	if err := json.Unmarshal(req.Object.Raw, pod); err != nil {
		return nil, false, err
	}

	rawPod := pod.DeepCopyObject()
	if !strings.HasPrefix(pod.Name, "importer-vm") {
		return nil, false, nil
	}
	nodeName, ok := p.cache.Load(pod.Name)
	if !ok {
		nodeName = p.Next().Name
	}

	pod.Spec.NodeSelector["kubernetes.io/hostname"] = nodeName.(string)

	mutatedData, err = json.Marshal(pod)
	if err != nil {
		return nil, false, err
	}
	p.cache.Store(pod.Name, nodeName)
	slog.Info("mutate pod",
		"ns", req.Namespace,
		"name", req.Name,
		"nodeName", nodeName.(string))

	return mutatedData, !reflect.DeepEqual(rawPod, pod), nil
}

func main() {
	conf, err := loadConfig()
	if err != nil {
		panic(err)
	}
	svc, err := NewService()
	if err != nil {
		panic(err)
	}

	http.Handle("/mutate", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req admissionv1.AdmissionRequest
		var err error
		if err = json.NewDecoder(r.Body).Decode(&req); err != nil {
			slog.Error("decode request failed", "err", err)
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		defer func() {
			if err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			if err := r.Body.Close(); err != nil {
				slog.Error("close request body failed", "err", err)
			}
		}()
		pod := &corev1.Pod{}
		if err := json.Unmarshal(req.Object.Raw, pod); err != nil {
			slog.Error("unmarshal pod failed", "err", err)
			return
		}

		nodeName, ok := svc.cache.Load(pod.Name)
		if !ok {
			nodeName = svc.Next().Name
		}
		pod.Spec.NodeSelector["kubernetes.io/hostname"] = nodeName.(string)

		mutatedData, err := json.Marshal(pod)
		if err != nil {
			slog.Error("marshal pod failed", "err", err)
			return
		}
		svc.cache.Store(pod.Name, nodeName)
		slog.Info("mutate pod",
			"ns", req.Namespace,
			"name", req.Name,
			"nodeName", nodeName.(string))
		_, err = jsonpatch.CreatePatch(req.Object.Raw, mutatedData)
		if err != nil {
			slog.Error("create patch failed", "err", err)
			return
		}

		resp := admissionv1.AdmissionReview{
			TypeMeta: metav1.TypeMeta{
				Kind:       "AdmissionReview",
				APIVersion: "admission.k8s.io/v1",
			},
			Response: &admissionv1.AdmissionResponse{
				UID:     req.UID,
				Allowed: true,
			},
		}
		if err := json.NewEncoder(w).Encode(&resp); err != nil {
			slog.Error("encode response failed", "err", err)
			return
		}
	}))

	if err = http.ListenAndServeTLS(conf.Address, conf.TLS.CertFile, conf.TLS.KeyFile, nil); err != nil {
		panic(err)
	}
}
