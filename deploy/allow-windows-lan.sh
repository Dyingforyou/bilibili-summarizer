#!/usr/bin/env bash
# Run on the Linux host with sudo. Opens only the two IPv4 addresses reported by Windows.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "请在 Linux 机器上运行：sudo bash deploy/allow-windows-lan.sh" >&2
    exit 1
fi

if [[ $(firewall-cmd --state) != running ]]; then
    echo "firewalld 未运行；没有修改防火墙。" >&2
    exit 1
fi

zone=$(firewall-cmd --get-zone-of-interface=enp6s0 2>/dev/null || true)
if [[ -z $zone || $zone == "no zone" ]]; then
    zone=$(firewall-cmd --get-default-zone)
fi

for client_ip in 192.168.1.105 192.168.1.108; do
    rule="rule family=\"ipv4\" source address=\"${client_ip}/32\" port port=\"8002\" protocol=\"tcp\" accept"
    if ! firewall-cmd --permanent --zone="$zone" --query-rich-rule="$rule" >/dev/null; then
        firewall-cmd --permanent --zone="$zone" --add-rich-rule="$rule"
    fi
    if ! firewall-cmd --zone="$zone" --query-rich-rule="$rule" >/dev/null; then
        firewall-cmd --zone="$zone" --add-rich-rule="$rule"
    fi
done

echo "已在 firewalld 区域 $zone 放行 192.168.1.105、192.168.1.108 到本机 TCP 8002；仅限这两个源地址。"
firewall-cmd --zone="$zone" --list-rich-rules | grep 'port="8002"' || true
