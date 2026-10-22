#!/usr/bin/env python3
"""验证 Calico + kube-proxy 数据路径，并保存真实命令输出。"""
import json
from pathlib import Path
import select
import subprocess
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "evidence"
OUT.mkdir(exist_ok=True)
CLUSTER = "pod-network-calico"
NODE = CLUSTER + "-worker"
REMOTE = CLUSTER + "-worker2"
K = ["docker", "exec", "-i", CLUSTER + "-control-plane", "kubectl", "--kubeconfig=/etc/kubernetes/admin.conf"]


def run(args, *, stdin=None):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stdout}\n{result.stderr}")
    return result.stdout


def save(name, text):
    (OUT / name).write_text(text)


def k(*args, stdin=None):
    return run(K + list(args), stdin=stdin)


def node(*args, host=NODE):
    return run(["docker", "exec", host, *args])


def get(url, pod="client"):
    code = "import urllib.request,sys; print(urllib.request.urlopen(sys.argv[1],timeout=2).read().decode())"
    return json.loads(k("-n", "pod-network", "exec", pod, "--", "python", "-c", code, url))


def capture(name, interface, expression, request):
    command = ["docker", "exec", NODE, "timeout", "12", "tcpdump", "-l", "-n", "-vv", "-i", interface, "-c", "4", expression]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # 监听就绪后才发请求，避免固定 sleep 掩盖抓包启动时序。
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            if select.select([process.stderr], [], [], 1)[0]:
                line = process.stderr.readline()
                if "listening on" in line:
                    ready = True
                    break
                if process.poll() is not None:
                    raise RuntimeError(line)
        if not ready:
            raise RuntimeError("tcpdump 未就绪")
        response = request()
        output, errors = process.communicate(timeout=15)
        if process.returncode != 0:
            raise RuntimeError(f"抓包未达到 4 包: {output}\n{errors}")
        save(name + ".txt", output + errors)
        return response
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def wait_request(url, allowed):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            result = get(url)
            if allowed:
                return result
        except RuntimeError as error:
            if not allowed and "timed out" in str(error):
                return {"result": "timed out"}
            if "timed out" not in str(error) and not (allowed and "Connection refused" in str(error)):
                raise
        time.sleep(0.5)  # 有截止时间的状态轮询，不把延时本身视为就绪。
    raise RuntimeError(f"策略未收敛: allowed={allowed}")


def main():
    k("-n", "pod-network", "wait", "--for=condition=Ready", "pod", "--all", "--timeout=180s")
    pods = json.loads(k("-n", "pod-network", "get", "pods", "-o", "json"))
    addresses = {p["metadata"]["name"]: p["status"]["podIP"] for p in pods["items"]}
    service = json.loads(k("-n", "pod-network", "get", "svc", "remote", "-o", "json"))
    vip = service["spec"]["clusterIP"]
    local_url = f"http://{addresses['local']}:8080/"
    remote_url = f"http://{addresses['remote']}:8080/"
    service_url = f"http://{vip}/"
    node_ip = json.loads(run(["docker", "inspect", NODE]))[0]["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
    save("topology.json", json.dumps({"pods": addresses, "service": vip, "client_node": node_ip}, indent=2) + "\n")
    save("versions.txt", k("version") + node("uname", "-r") + k("-n", "kube-system", "get", "ds", "-o", "wide"))
    save("ippools.json", k("get", "ippools.crd.projectcalico.org", "-o", "json"))
    save("endpointslices.json", k("-n", "pod-network", "get", "endpointslices", "-o", "json"))
    save("kube-proxy.txt", k("-n", "kube-system", "get", "cm", "kube-proxy", "-o", "jsonpath={.data.config\\.conf}"))
    sandbox = node("crictl", "pods", "--name", "client", "-q").strip()
    pid = str(json.loads(node("crictl", "inspectp", sandbox))["info"]["pid"])
    save("pod-network.txt", node("nsenter", "-t", pid, "-n", "ip", "-4", "addr") + node("nsenter", "-t", pid, "-n", "ip", "route"))
    local_route = json.loads(node("ip", "-j", "route", "get", addresses["client"]))[0]
    veth = local_route["dev"]
    save("proxy-arp.txt", node("sysctl", f"net.ipv4.conf.{veth}.proxy_arp", f"net.ipv4.neigh.{veth}.proxy_delay", f"net.ipv4.conf.{veth}.forwarding") + node("ip", "-4", "addr", "show", "dev", veth))
    for host in [NODE, REMOTE]:
        save(host + "-routes.txt", node("ip", "route", host=host) + node("ip", "-d", "link", "show", "vxlan.calico", host=host) + node("bridge", "fdb", "show", "dev", "vxlan.calico", host=host) + node("ip", "neigh", "show", "dev", "vxlan.calico", host=host))
    results = {}
    results["same_node"] = get(local_url)
    results["clusterip_before_dnat"] = capture("clusterip-before-dnat", veth, f"host {vip} and tcp port 80", lambda: get(service_url))
    results["cross_node"] = capture("cross-node-vxlan", "eth0", "udp port 4789", lambda: get(remote_url))
    results["cluster_ip"] = capture("clusterip-vxlan", "eth0", "udp port 4789", lambda: get(service_url))
    for filename in ["cross-node-vxlan.txt", "clusterip-vxlan.txt"]:
        packets = (OUT / filename).read_text()
        assert addresses["client"] in packets and addresses["remote"] in packets and ".4789" in packets, packets
    results["dns_service"] = get("http://remote.pod-network.svc.cluster.local/")
    for case in ["same_node", "cross_node", "cluster_ip", "dns_service"]:
        assert results[case]["peer"] == addresses["client"], (case, results[case])
    results["hairpin"] = get(service_url, pod="remote")
    assert results["hairpin"]["peer"] != addresses["remote"], results["hairpin"]

    # 独立 Docker 容器作为集群外目标，不依赖公网第三方服务。
    server_code = k("-n", "pod-network", "get", "cm", "echo-server", "-o", "jsonpath={.data.server\\.py}")
    external = CLUSTER + "-outside"
    run(["docker", "run", "-d", "--name", external, "--network", "kind", "python:3.12-alpine", "python", "-u", "-c", server_code])
    try:
        external_ip = json.loads(run(["docker", "inspect", external]))[0]["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
        results["outgoing"] = wait_request(f"http://{external_ip}:8080/", True)
        assert results["outgoing"]["peer"] == node_ip, results["outgoing"]
        code = "import urllib.request,sys; print(urllib.request.urlopen(sys.argv[1],timeout=3).read().decode())"
        results["nodeport_cluster"] = json.loads(run(["docker", "exec", external, "python", "-c", code, f"http://{node_ip}:30080/"]))
        route = json.loads(node("ip", "-j", "route", "get", addresses["remote"]))[0]
        assert results["nodeport_cluster"]["peer"] == route["prefsrc"], (results["nodeport_cluster"], route)
        save("remote-route-get.json", json.dumps(route, indent=2) + "\n")
        results["external_ip"] = external_ip
    finally:
        run(["docker", "rm", "-f", external])
    save("nat-rules.txt", node("iptables-save", "-c", "-t", "nat"))
    save("remote-nat-rules.txt", node("iptables-save", "-c", "-t", "nat", host=REMOTE))
    save("iptables-version.txt", node("iptables", "--version"))
    save("conntrack.txt", node("conntrack", "-L", "-p", "tcp"))
    k("apply", "-f", "-", stdin=(ROOT / "policy.yaml").read_text())
    try:
        results["policy_direct_denied"] = wait_request(remote_url, False)
        results["policy_service_denied"] = wait_request(service_url, False)
        results["policy_local_control"] = get(local_url)
        save("policy-denied-rules.txt", node("iptables-save", "-c", "-t", "filter", host=REMOTE))
        save("policy-denied-ipsets.txt", node("ipset", "save", host=REMOTE))
        k("-n", "pod-network", "label", "pod", "client", "allowed=true", "--overwrite")
        results["policy_direct_allowed"] = wait_request(remote_url, True)
        results["policy_service_allowed"] = wait_request(service_url, True)
        save("policy-allowed-rules.txt", node("iptables-save", "-c", "-t", "filter", host=REMOTE))
        save("policy-allowed-ipsets.txt", node("ipset", "save", host=REMOTE))
    finally:
        k("-n", "pod-network", "delete", "networkpolicy", "remote-ingress")
        k("-n", "pod-network", "label", "pod", "client", "allowed-")
    save("results.json", json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    print("PASS: Pod 路由、VXLAN、Service、DNS、hairpin、出站 NAT、NodePort 和策略变更")


if __name__ == "__main__":
    main()
