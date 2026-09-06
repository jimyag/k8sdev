// 基础实验程序：提供 CPU 忙循环、可控队列 gauge，以及持续请求负载。
package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync/atomic"
	"time"
)

// 多个 HTTP 请求可能并发修改和读取队列长度，因此使用原子变量。
var depth atomic.Int64

// 根据启动参数选择负载模式；默认启动指标与工作接口。
func main() {
	// 8 个并发循环只负责持续施压，不保证固定吞吐或测量业务延迟。
	if len(os.Args) > 1 && os.Args[1] == "load" {
		for i := 0; i < 8; i++ {
			go func() {
				client := &http.Client{Timeout: 5 * time.Second}
				for {
					res, err := client.Get("http://worker:8080/work")
					if err == nil {
						res.Body.Close()
					} else {
						time.Sleep(time.Second)
					}
				}
			}()
		}
		select {}
	}
	// 就绪探针只确认 HTTP 服务可用。
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { fmt.Fprintln(w, "ok") })
	// 约 100ms 的忙循环制造 CPU 压力；这里不是实际业务计算。
	http.HandleFunc("/work", func(w http.ResponseWriter, r *http.Request) {
		end := time.Now().Add(100 * time.Millisecond)
		for time.Now().Before(end) {
		}
		fmt.Fprintln(w, "done")
	})
	// 只允许 POST 修改非负模拟队列长度；此接口仅用于独立本地实验。
	http.HandleFunc("/set", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "POST required", 405)
			return
		}
		n, err := strconv.ParseInt(r.URL.Query().Get("value"), 10, 64)
		if err != nil || n < 0 {
			http.Error(w, "nonnegative integer required", 400)
			return
		}
		depth.Store(n)
		fmt.Fprintln(w, n)
	})
	// 导出可增可减的 gauge，数值由测试脚本控制，不会被 worker 消费。
	http.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprintf(w, "# HELP demo_queue_depth Synthetic global queue depth.\n# TYPE demo_queue_depth gauge\ndemo_queue_depth %d\n", depth.Load())
	})
	log.Fatal(http.ListenAndServe(":8080", nil))
}
