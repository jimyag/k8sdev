package main

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func TestWebAppSpecFromDefaultsOptionalFields(t *testing.T) {
	webApp := &unstructured.Unstructured{Object: map[string]any{
		"spec": map[string]any{"image": "nginx:1.27-alpine"},
	}}

	spec, err := webAppSpecFrom(webApp)
	if err != nil {
		t.Fatalf("webAppSpecFrom() error = %v", err)
	}
	if spec.Image != "nginx:1.27-alpine" || spec.Replicas != 1 || spec.Port != 80 {
		t.Fatalf("webAppSpecFrom() = %#v, want image plus defaults", spec)
	}
}

func TestWebAppSpecFromRequiresImage(t *testing.T) {
	_, err := webAppSpecFrom(&unstructured.Unstructured{Object: map[string]any{
		"spec": map[string]any{},
	}})
	if err == nil {
		t.Fatal("webAppSpecFrom() error = nil, want missing image error")
	}
}
