package main

import (
	"context"
	"fmt"
	"log"
	"reflect"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/util/intstr"
)

const (
	appLabel      = "app.kubernetes.io/name"
	instanceLabel = "app.kubernetes.io/instance"
)

type webAppSpec struct {
	Image    string
	Replicas int32
	Port     int32
}

func (c *controller) reconcileWebApp(ctx context.Context, webApp *unstructured.Unstructured) (bool, error) {
	spec, err := webAppSpecFrom(webApp)
	if err != nil {
		return false, err
	}

	labels := map[string]string{
		appLabel:      "webapp",
		instanceLabel: webApp.GetName(),
	}
	deployment, err := c.ensureDeployment(ctx, webApp, spec, labels)
	if err != nil {
		return false, err
	}
	if err := c.ensureService(ctx, webApp, spec, labels); err != nil {
		return false, err
	}

	ready := deployment.Status.ReadyReplicas
	if err := c.updateStatus(ctx, webApp, spec, deployment); err != nil {
		return false, err
	}
	log.Printf("reconciled %s/%s: replicas=%d ready=%d", webApp.GetNamespace(), webApp.GetName(), spec.Replicas, ready)
	return ready < spec.Replicas, nil
}

func webAppSpecFrom(webApp *unstructured.Unstructured) (webAppSpec, error) {
	image, found, err := unstructured.NestedString(webApp.Object, "spec", "image")
	if err != nil {
		return webAppSpec{}, fmt.Errorf("read spec.image: %w", err)
	}
	if !found || image == "" {
		return webAppSpec{}, fmt.Errorf("spec.image is required")
	}
	replicas, found, err := unstructured.NestedInt64(webApp.Object, "spec", "replicas")
	if err != nil {
		return webAppSpec{}, fmt.Errorf("read spec.replicas: %w", err)
	}
	if !found {
		replicas = 1
	}
	port, found, err := unstructured.NestedInt64(webApp.Object, "spec", "port")
	if err != nil {
		return webAppSpec{}, fmt.Errorf("read spec.port: %w", err)
	}
	if !found {
		port = 80
	}
	return webAppSpec{Image: image, Replicas: int32(replicas), Port: int32(port)}, nil
}

func (c *controller) ensureDeployment(ctx context.Context, webApp *unstructured.Unstructured, spec webAppSpec, labels map[string]string) (*appsv1.Deployment, error) {
	deployments := c.clientset.AppsV1().Deployments(webApp.GetNamespace())
	desired := desiredDeployment(webApp, spec, labels)
	existing, err := deployments.Get(ctx, webApp.GetName(), metav1.GetOptions{})
	if apierrors.IsNotFound(err) {
		return deployments.Create(ctx, desired, metav1.CreateOptions{})
	}
	if err != nil {
		return nil, err
	}
	if !equality.Semantic.DeepEqual(existing.Spec.Template, desired.Spec.Template) ||
		!equality.Semantic.DeepEqual(existing.Spec.Replicas, desired.Spec.Replicas) ||
		!reflect.DeepEqual(existing.Labels, desired.Labels) {
		existing.Spec.Replicas = desired.Spec.Replicas
		existing.Spec.Template = desired.Spec.Template
		existing.Labels = desired.Labels
		return deployments.Update(ctx, existing, metav1.UpdateOptions{})
	}
	return existing, nil
}

func desiredDeployment(webApp *unstructured.Unstructured, spec webAppSpec, labels map[string]string) *appsv1.Deployment {
	controllerRef := metav1.NewControllerRef(webApp, schema.GroupVersionKind{
		Group: "apps.demo.example.com", Version: "v1", Kind: "WebApp",
	})
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:            webApp.GetName(),
			Namespace:       webApp.GetNamespace(),
			Labels:          labels,
			OwnerReferences: []metav1.OwnerReference{*controllerRef},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &spec.Replicas,
			Selector: &metav1.LabelSelector{MatchLabels: labels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{Containers: []corev1.Container{{
					Name:            "web",
					Image:           spec.Image,
					ImagePullPolicy: corev1.PullIfNotPresent,
					Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: spec.Port}},
					ReadinessProbe: &corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{
							Path: "/", Port: intstr.FromInt32(spec.Port),
						}},
						InitialDelaySeconds: 1,
						PeriodSeconds:       2,
					},
				}}},
			},
		},
	}
}

func (c *controller) ensureService(ctx context.Context, webApp *unstructured.Unstructured, spec webAppSpec, labels map[string]string) error {
	services := c.clientset.CoreV1().Services(webApp.GetNamespace())
	desired := desiredService(webApp, spec, labels)
	existing, err := services.Get(ctx, webApp.GetName(), metav1.GetOptions{})
	if apierrors.IsNotFound(err) {
		_, err := services.Create(ctx, desired, metav1.CreateOptions{})
		return err
	}
	if err != nil {
		return err
	}
	desired.Spec.ClusterIP = existing.Spec.ClusterIP
	desired.Spec.ClusterIPs = existing.Spec.ClusterIPs
	desired.Spec.IPFamilies = existing.Spec.IPFamilies
	desired.Spec.IPFamilyPolicy = existing.Spec.IPFamilyPolicy
	if !equality.Semantic.DeepEqual(existing.Spec.Selector, desired.Spec.Selector) ||
		!equality.Semantic.DeepEqual(existing.Spec.Ports, desired.Spec.Ports) ||
		!reflect.DeepEqual(existing.Labels, desired.Labels) {
		existing.Spec.Selector = desired.Spec.Selector
		existing.Spec.Ports = desired.Spec.Ports
		existing.Labels = desired.Labels
		_, err := services.Update(ctx, existing, metav1.UpdateOptions{})
		return err
	}
	return nil
}

func desiredService(webApp *unstructured.Unstructured, spec webAppSpec, labels map[string]string) *corev1.Service {
	controllerRef := metav1.NewControllerRef(webApp, schema.GroupVersionKind{
		Group: "apps.demo.example.com", Version: "v1", Kind: "WebApp",
	})
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:            webApp.GetName(),
			Namespace:       webApp.GetNamespace(),
			Labels:          labels,
			OwnerReferences: []metav1.OwnerReference{*controllerRef},
		},
		Spec: corev1.ServiceSpec{
			Selector: labels,
			Ports:    []corev1.ServicePort{{Name: "http", Port: spec.Port, TargetPort: intstr.FromInt32(spec.Port)}},
		},
	}
}

func (c *controller) updateStatus(ctx context.Context, webApp *unstructured.Unstructured, spec webAppSpec, deployment *appsv1.Deployment) error {
	available := deployment.Status.AvailableReplicas >= spec.Replicas
	conditionStatus := "False"
	conditionType := "Progressing"
	reason := "WaitingForDeployment"
	message := fmt.Sprintf("%d/%d replicas are ready", deployment.Status.ReadyReplicas, spec.Replicas)
	if available {
		conditionStatus = "True"
		conditionType = "Available"
		reason = "DeploymentReady"
		message = "all requested replicas are available"
	}
	status := map[string]any{
		"observedGeneration": webApp.GetGeneration(),
		"readyReplicas":      int64(deployment.Status.ReadyReplicas),
		"availableReplicas":  int64(deployment.Status.AvailableReplicas),
		"conditions": []any{map[string]any{
			"type":    conditionType,
			"status":  conditionStatus,
			"reason":  reason,
			"message": message,
		}},
	}
	current, _, err := unstructured.NestedFieldCopy(webApp.Object, "status")
	if err != nil {
		return err
	}
	if equality.Semantic.DeepEqual(current, status) {
		return nil
	}
	updated := webApp.DeepCopy()
	updated.Object["status"] = status
	_, err = c.dynamicClient.Resource(webAppGVR).Namespace(webApp.GetNamespace()).UpdateStatus(ctx, updated, metav1.UpdateOptions{})
	return err
}
