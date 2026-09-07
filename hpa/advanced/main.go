// 进阶实验程序：内存任务队列、可优雅退出的消费者，以及每 Pod HTTP 请求计数。
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Task 记录任务领取与确认状态；Done 防止重复 ACK，Attempts 用于核对重投。
type Task struct {
	ID         int       `json:"id"`
	DurationMS int       `json:"duration_ms"`
	Worker     string    `json:"worker"`
	Attempts   int       `json:"attempts"`
	Deadline   time.Time `json:"deadline"`
	Done       bool      `json:"done"`
}

// Event 保存带 UTC 时间的任务事件，供吞吐对比和缩容后的任务审计使用。
type Event struct {
	Time   time.Time `json:"time"`
	Kind   string    `json:"kind"`
	ID     int       `json:"id"`
	Worker string    `json:"worker"`
}

var mu sync.Mutex
var tasks []*Task
var events []Event
var requests atomic.Int64

// 只累计 /upload 完整读取的请求体字节，不包含 HTTP 头和网络协议开销。
var processedBytes atomic.Int64
var draining atomic.Bool
var born = time.Now()
var client = &http.Client{Timeout: 5 * time.Second}

// 读取整数环境变量；未设置或格式错误时使用实验默认值。
func envInt(name string, fallback int) int {
	n, e := strconv.Atoi(os.Getenv(name))
	if e != nil {
		return fallback
	}
	return n
}

// 追加任务审计事件；调用方须持有队列互斥锁。
func record(kind string, id int, worker string) {
	events = append(events, Event{time.Now().UTC(), kind, id, worker})
}

// 释放已过期且未完成的领取租约，允许其他 consumer 重领任务。
func reap() {
	for _, t := range tasks {
		if !t.Done && t.Worker != "" && time.Now().After(t.Deadline) {
			record("expired", t.ID, t.Worker)
			t.Worker = ""
		}
	}
}

// 分别统计未领取、执行中、已完成任务和额外领取次数；调用方须持锁。
func counts() (pending, inflight, done, retries int) {
	for _, t := range tasks {
		if t.Done {
			done++
		} else if t.Worker != "" {
			inflight++
		} else {
			pending++
		}
		if t.Attempts > 1 {
			retries += t.Attempts - 1
		}
	}
	return
}

// 通过 broker Service 发送领取或确认请求，并将非成功响应作为错误返回。
func post(path string) ([]byte, error) {
	resp, err := client.Post("http://broker:8080"+path, "text/plain", nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("%s: %s", resp.Status, b)
	}
	return b, err
}

// 每个 consumer 同时处理一个任务；取消后不再领取，已领取任务仍会执行并 ACK。
func consumer(ctx context.Context, done chan struct{}) {
	defer close(done)
	worker := os.Getenv("HOSTNAME")
	for {
		if ctx.Err() != nil {
			return
		}
		b, err := post("/claim?worker=" + url.QueryEscape(worker))
		if err != nil {
			log.Printf("claim: %v", err)
			time.Sleep(time.Second)
			continue
		}
		var t Task
		if json.Unmarshal(b, &t) != nil || t.ID == 0 {
			select {
			case <-ctx.Done():
				return
			case <-time.After(200 * time.Millisecond):
			}
			continue
		}
		log.Printf("claim id=%d duration_ms=%d", t.ID, t.DurationMS)
		// SIGTERM 不打断当前任务；完成并 ACK 后，下一轮循环检测取消并退出。
		time.Sleep(time.Duration(t.DurationMS) * time.Millisecond)
		_, err = post(fmt.Sprintf("/ack?id=%d&worker=%s", t.ID, url.QueryEscape(worker)))
		if err != nil {
			log.Printf("ack_failed id=%d error=%v", t.ID, err)
		} else {
			log.Printf("ack id=%d draining=%v", t.ID, ctx.Err() != nil)
		}
	}
}

// 按参数选择 broker、consumer、HTTP 服务或定速负载模式。
func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds | log.LUTC)
	mode := "http"
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}
	// 按目标 RPS 发起请求；关闭 keepalive，让新连接经 Service 分配给不同 Pod。
	if mode == "load" {
		rate := envInt("RPS", 40)
		transport := &http.Transport{DisableKeepAlives: true}
		c := &http.Client{Transport: transport, Timeout: 5 * time.Second}
		target := os.Getenv("TARGET")
		if target == "" {
			target = "http://web:8080/request"
		}
		// 带宽实验发送真实请求体；零字节保持原 GET 请求模式。
		payloadSize := envInt("PAYLOAD_BYTES", 0)
		if rate <= 0 || rate > 1000 || payloadSize < 0 || payloadSize > 8*1024*1024 {
			log.Fatal("RPS must be 1..1000; PAYLOAD_BYTES must be 0..8388608")
		}
		payload := make([]byte, payloadSize)
		ticker := time.NewTicker(time.Second / time.Duration(rate))
		defer ticker.Stop()
		for range ticker.C {
			go func() {
				var r *http.Response
				var e error
				if payloadSize > 0 {
					r, e = c.Post(target, "application/octet-stream", bytes.NewReader(payload))
				} else {
					r, e = c.Get(target)
				}
				if e == nil {
					io.Copy(io.Discard, r.Body)
					r.Body.Close()
				}
			}()
		}
		return
	}
	// 将系统终止信号转换为取消通知，协调消费者与 HTTP 服务退出。
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	mux := http.NewServeMux()
	// 可注入 60 秒就绪延迟，用来区分 Running 与 Ready。
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if draining.Load() || time.Since(born) < time.Duration(envInt("READY_DELAY_SECONDS", 0))*time.Second {
			http.Error(w, "not ready", 503)
			return
		}
		fmt.Fprintln(w, "ok")
	})
	// 累计每个 Pod 成功处理的请求数，Prometheus 再通过 rate() 转成速率。
	mux.HandleFunc("/request", func(w http.ResponseWriter, r *http.Request) { requests.Add(1); fmt.Fprintln(w, "ok") })
	// 读取真实上传数据；失败请求不计入完成数，限制单次请求体最多 8 MiB。
	mux.HandleFunc("/upload", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST required", http.StatusMethodNotAllowed)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 8*1024*1024)
		n, err := io.Copy(io.Discard, r.Body)
		if err != nil {
			http.Error(w, "incomplete or oversized body", http.StatusBadRequest)
			return
		}
		processedBytes.Add(n)
		requests.Add(1)
		fmt.Fprintf(w, "processed_bytes=%d\n", n)
	})
	// 保留 CPU 压力接口，方便区分资源指标与业务指标的作用。
	mux.HandleFunc("/work", func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		end := time.Now().Add(100 * time.Millisecond)
		for time.Now().Before(end) {
		}
		fmt.Fprintln(w, "ok")
	})
	// pending 不含 inflight；任务都被领取后，指标可为零但任务仍在执行。
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprintf(w, "# TYPE demo_http_requests_total counter\ndemo_http_requests_total %d\n", requests.Load())
		fmt.Fprintf(w, "# TYPE demo_processed_bytes_total counter\ndemo_processed_bytes_total %d\n", processedBytes.Load())
		if mode == "broker" {
			mu.Lock()
			defer mu.Unlock()
			reap()
			p, i, d, re := counts()
			fmt.Fprintf(w, "# TYPE task_queue_depth gauge\ntask_queue_depth %d\n# TYPE task_inflight gauge\ntask_inflight %d\n# TYPE task_completed_total counter\ntask_completed_total %d\n# TYPE task_retries_total counter\ntask_retries_total %d\n", p, i, d, re)
		}
	})
	if mode == "broker" {
		// 生成有唯一 ID 的内存任务；限制数量与耗时，避免实验失控。
		mux.HandleFunc("/enqueue", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "POST" {
				http.Error(w, "POST required", 405)
				return
			}
			n, e := strconv.Atoi(r.URL.Query().Get("n"))
			ms, e2 := strconv.Atoi(r.URL.Query().Get("duration_ms"))
			if e != nil || e2 != nil || n < 1 || n > 1000 || ms < 1 || ms > 90000 {
				http.Error(w, "n 1..1000, duration_ms 1..90000", 400)
				return
			}
			mu.Lock()
			defer mu.Unlock()
			for j := 0; j < n; j++ {
				id := len(tasks) + 1
				tasks = append(tasks, &Task{ID: id, DurationMS: ms})
				record("enqueue", id, "")
			}
			fmt.Fprintln(w, len(tasks))
		})
		// 持锁选择未领取任务；租约比预计处理时长多 20 秒，留出确认时间。
		mux.HandleFunc("/claim", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "POST" {
				http.Error(w, "POST required", 405)
				return
			}
			worker := r.URL.Query().Get("worker")
			if worker == "" {
				http.Error(w, "worker required", 400)
				return
			}
			mu.Lock()
			defer mu.Unlock()
			reap()
			for _, t := range tasks {
				if !t.Done && t.Worker == "" {
					t.Worker = worker
					t.Attempts++
					t.Deadline = time.Now().Add(time.Duration(t.DurationMS)*time.Millisecond + 20*time.Second)
					record("claim", t.ID, worker)
					json.NewEncoder(w).Encode(t)
					return
				}
			}
			json.NewEncoder(w).Encode(Task{})
		})
		// 只有当前领取者才能确认尚未完成的任务；过期或重复确认会记录并拒绝。
		mux.HandleFunc("/ack", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "POST" {
				http.Error(w, "POST required", 405)
				return
			}
			id, e := strconv.Atoi(r.URL.Query().Get("id"))
			worker := r.URL.Query().Get("worker")
			mu.Lock()
			defer mu.Unlock()
			reap()
			if e != nil || id < 1 || id > len(tasks) {
				http.Error(w, "unknown id", 400)
				return
			}
			t := tasks[id-1]
			if t.Done || t.Worker != worker {
				record("rejected_ack", id, worker)
				http.Error(w, "stale or duplicate ack", 409)
				return
			}
			t.Done = true
			record("ack", id, worker)
			fmt.Fprintln(w, "ok")
		})
		// 返回计数、任务明细和事件，供测试核对任务守恒及重投次数。
		mux.HandleFunc("/stats", func(w http.ResponseWriter, r *http.Request) {
			mu.Lock()
			defer mu.Unlock()
			reap()
			p, i, d, re := counts()
			json.NewEncoder(w).Encode(map[string]any{"accepted": len(tasks), "pending": p, "inflight": i, "completed": d, "retries": re, "tasks": tasks, "events": events})
		})
	}
	done := make(chan struct{})
	if mode == "consumer" {
		go consumer(ctx, done)
	} else {
		close(done)
	}
	server := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		if e := server.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			log.Fatal(e)
		}
	}()
	// 停止接新任务后等待当前任务完成；终止宽限期由 Pod 配置提供。
	<-ctx.Done()
	draining.Store(true)
	log.Printf("SIGTERM: stop claiming; wait for current task")
	<-done
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	server.Shutdown(shutdown)
	log.Printf("drained; exit")
}
