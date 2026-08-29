# Hermes Link Server Docker 直接 HTTP 部署说明

此路径用于已安装 Docker Engine 与 Compose 的 Linux 主机。它直接启动 Hermes
Link Server 的 HTTP 监听，不启动或管理 Caddy，不申请域名证书，也不需要公网
`80` 端口。

## 前置条件

- Hermes Agent 已在本机正常运行，且保持在回环地址；
- 手机可访问服务器 IP 和选定的 TCP 端口；
- 端口范围为 `1024..65535`，例如 `18766`；
- 仅在可信 LAN/VPN 使用 HTTP。HTTP 会传输设备 Token，不适合直接暴露到公网。

## 部署

```bash
sudo bash scripts/docker-deploy.sh \
  --public-base-url http://192.168.1.10:18766 \
  --port 18766 \
  --dry-run
```

确认后去掉 `--dry-run`。脚本会创建不显示的内部 Agent 凭据、发现 Profile、以
`0.0.0.0:18766` 启动 Server，并在终端输出一次性配对二维码。App 使用「设置 →
服务器 → 扫码配置」扫描即可。

## 检查与排障

```bash
curl --fail http://127.0.0.1:18766/health
sudo docker compose -f deploy/docker/compose.yaml ps
```

如果手机无法连接，依次检查服务器 IP 是否正确、端口是否已放行、手机是否在可信
网络，以及 Hermes Agent 是否仍只监听本机回环地址。不要把 Agent 的 `8642`/`8080`
端口或内部凭据暴露给公网。

如需 HTTPS 域名，请自行申请证书并配置反向代理到该 HTTP 端口；这不是 Docker
部署脚本管理的职责。
