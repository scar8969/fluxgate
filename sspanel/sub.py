"""Subscription link generation — mirrors apps/sub in the original.

Generates client-ready subscription payloads for:
  - ss://      (shadowsocks, SIP002 URI)
  - vmess://   (v2ray, base64 JSON)
  - vless://   (v2ray vless URI)
  - trojan://  (trojan URI)
  - clash YAML (proxies + rules)
"""
import base64
import json
from urllib.parse import quote

from .models import User
from .proxy import ProxyNode


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _ss_uri(node, user):
    # SIP002: ss://base64(method:password)@server:port#name
    payload = f"{node.ss_method}:{user.ss_password}"
    return f"ss://{_b64(payload)}@{node.multi_server_address[0]}:{node.ss_port}#{quote(node.name)}"


def _vmess_uri(node, user):
    vmess = {
        "v": "2",
        "ps": node.name,
        "add": node.multi_server_address[0],
        "port": str(node.ss_port),
        "id": user.vmess_uuid or node.uuid,
        "aid": "0",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": "",
    }
    return "vmess://" + _b64(json.dumps(vmess, ensure_ascii=False))


def _vless_uri(node, user):
    uid = user.vmess_uuid or node.uuid
    return (
        f"vless://{uid}@{node.multi_server_address[0]}:{node.ss_port}"
        f"?type=tcp&security=none#{quote(node.name)}"
    )


def _trojan_uri(node, user):
    pw = node.trojan_password or user.ss_password
    return f"trojan://{pw}@{node.multi_server_address[0]}:{node.ss_port}#{quote(node.name)}"


def _clash_yaml(node, user):
    """Generate a Clash proxy entry + full config for the node."""
    if node.node_type == ProxyNode.NODE_TYPE_SS:
        proxy = {
            "name": node.name,
            "type": "ss",
            "server": node.multi_server_address[0],
            "port": node.ss_port,
            "cipher": node.ss_method,
            "password": user.ss_password,
        }
    elif node.node_type == ProxyNode.NODE_TYPE_TROJAN:
        proxy = {
            "name": node.name,
            "type": "trojan",
            "server": node.multi_server_address[0],
            "port": node.ss_port,
            "password": node.trojan_password or user.ss_password,
        }
    else:  # vless
        proxy = {
            "name": node.name,
            "type": "vless",
            "server": node.multi_server_address[0],
            "port": node.ss_port,
            "uuid": user.vmess_uuid or node.uuid,
            "network": "tcp",
            "tls": False,
        }
    return proxy


def generate_subscription(user: User, sub_type: str = "ss"):
    """Return subscription text for the user, filtered by their level."""
    nodes = ProxyNode.get_active_nodes(level=user.level)
    lines = []
    for node in nodes:
        if sub_type == "ss":
            lines.append(_ss_uri(node, user))
        elif sub_type == "v2ray":
            lines.append(_vmess_uri(node, user))
        elif sub_type == "trojan":
            lines.append(_trojan_uri(node, user))
        elif sub_type == "clash":
            proxies = [_clash_yaml(node, user) for node in nodes]
            yaml_lines = ["proxies:"]
            for p in proxies:
                yaml_lines.append("  - " + json.dumps(p, ensure_ascii=False))
            yaml_lines.append("rules:")
            yaml_lines.append('  - "MATCH,DIRECT"')
            return "\n".join(yaml_lines)
        else:
            # default: all formats mixed (like the original's default sub)
            lines.append(_ss_uri(node, user))
            lines.append(_vmess_uri(node, user))
            lines.append(_trojan_uri(node, user))

    # standard subscription: base64-encoded list of URIs
    return _b64("\n".join(lines))


def generate_clash_config(user: User):
    """Full Clash config with proxies + proxy-groups + rules."""
    nodes = ProxyNode.get_active_nodes(level=user.level)
    proxies = [_clash_yaml(node, user) for node in nodes]
    names = [p["name"] for p in proxies]
    lines = ["mixed-port: 7890", "allow-lan: false", "mode: rule", "log-level: info", "proxies:"]
    for p in proxies:
        lines.append("  - " + json.dumps(p, ensure_ascii=False))
    lines.append("proxy-groups:")
    lines.append("  - name: PROXY")
    lines.append("    type: select")
    lines.append("    proxies: " + json.dumps(names, ensure_ascii=False))
    lines.append("rules:")
    lines.append('  - "MATCH,PROXY"')
    return "\n".join(lines)
