# Hermes Link Server Docker 全新环境一键部署说明

本说明用于 Linux 服务器上的 Hermes Link Server。它部署的是自托管
`Hermes Link Server`，不是 Hermes Link Cloud；聊天、会话、任务和 DIRECT
通知在不启用 Cloud 时仍可工作。

## 这条命令会做什么

首次部署时，脚本会：

1. 检查 Docker Engine 与 Docker Compose 插件；
2. 确保 Hermes Agent systemd 服务存在；服务不存在时，通过本机 `hermes`
   CLI 为指定 Linux 用户创建服务；
3. 本地生成一份随机的 Hermes Link 专用内部凭据；
4. 将凭据写入 `/etc/hermes-link-server/internal-agent.env`，权限为 `0600`；
5. 通过 systemd drop-in 将同一凭据注入 Hermes Agent；
6. 启动 Docker Server，并由 Caddy 提供 HTTPS；
7. 在终端打印一次性配对二维码。

因此，**不需要获取、粘贴或查看 Hermes Agent Token**。这个内部凭据只用于
`Hermes Link Server → Hermes Agent` 的本机回环通信；App 只通过二维码配对得到
自己的设备 Token。

## 前置条件

- Linux 主机；Docker Desktop 不支持本说明中的 host networking 模式。
- 已安装 Docker Engine 和 `docker compose` 插件。
- 已安装 Hermes Agent 的 `hermes` CLI，并已为运行 Agent 的 Linux 用户完成模型
  Provider 配置。Provider 账号/密钥不由 Hermes Link 安装器处理。
- 一个可解析到此服务器的 DNS 名称。
- 公网 HTTPS 端口；默认 `443`，也可用 `8443`、`18443` 等其他端口。
- Caddy 自动签发证书时，公网 TCP `80` 必须可达（HTTP-01 验证）；同时放行所选
  HTTPS 端口。

不要对外开放 `8642`（Hermes Agent）或 `8765`（Hermes Link Bridge）。二者只应
监听在 `127.0.0.1`。

## 首次部署

进入已经审阅的 `hermes-link-server` 发布目录，先执行 dry-run。下面以 `erp` 为
Hermes Agent 的 Linux 运行用户、`8443` 为公网端口为例：

```bash
cd /path/to/hermes-link-server

sudo bash scripts/docker-deploy.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --agent-run-as-user erp \
  --dry-run
```

dry-run 不会生成凭据、创建 systemd drop-in、启动容器或改动 Agent。确认输出中的
域名、HTTPS 端口、Bridge 回环端口均正确后，去掉 `--dry-run`：

```bash
sudo bash scripts/docker-deploy.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --agent-run-as-user erp
```

成功后，终端会输出一次性二维码。用 Hermes Link App 的“扫码配对”扫描即可；二维码
仅含短期配对码，默认 600 秒过期，不含内部凭据、设备 Token、Cloud 凭据或私钥。

如未显式指定 `--agent-run-as-user`，通过普通用户执行 `sudo bash ...` 时，脚本会使用
该 sudo 调用者。自动推断失败时，再显式提供该参数即可。

## 端口与 URL 规则

- `--public-base-url` 必须是完整 HTTPS Origin，例如
  `https://link.example.com:8443`。
- `--port` 必须与 URL 中的端口一致；省略端口时默认 `443`。
- App 可以使用非 443 端口，但二维码和 App 中的 Server 地址必须包含同一个端口。
- Caddy 使用 host networking，因此选择的 HTTPS 端口和 `80` 不能被其他本机服务
  占用。

部署后的只读检查：

```bash
curl --fail --silent https://link.example.com:8443/hermes-link/v1/server-info
sudo docker compose -f deploy/docker/compose.yaml ps
```

第一条命令应返回 Server capability 信息；它不需要打印或传入任何凭据。

## 轮换内部凭据

不要手工编辑 `/etc/hermes-link-server/internal-agent.env`。Docker 部署使用相同的
公共 URL 重新运行并增加 `--rotate`：

```bash
sudo bash scripts/docker-deploy.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --agent-run-as-user erp \
  --rotate
```

脚本会原子替换内部凭据、重启 Hermes Agent，然后强制重建 Docker Server 容器，使双方
加载相同的新值。该过程会短暂中断 Server 请求；既有 App 设备 Token 不会被打印或写入
二维码。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `hermes` CLI 不存在 | 先按 Hermes Agent 官方方式安装 Agent；不要尝试把 Provider 密钥写入 Hermes Link 配置。 |
| `8642` 被占用 | 新环境不应并行启动第二个 Agent；先停止测试进程或使用干净主机。 |
| `8765` 被占用 | 新环境不应已有 Bridge；确认没有遗留 Hermes Link 服务后再部署。 |
| Caddy 无法启动 | 检查本机 `80`、所选 HTTPS 端口是否已被其他服务占用，以及防火墙/DNS 是否正确。 |
| 扫码后配对失败 | 确认 App 的 URL、端口与二维码一致，并检查 Caddy 与 Docker Server 均正常运行。 |
| 配对后返回 503 | 检查 Agent 服务和 Docker Server 均正常运行；必要时通过同一部署命令加 `--rotate` 重新同步内部凭据。 |

## 安全边界

- 不要把 `internal-agent.env`、Docker 日志、二维码截图或 `/etc` 配置提交到 Git。
- 不要将 Hermes Agent、Bridge、Cloud 数据库或 Huawei Push 服务端凭据暴露给 App。
- Cloud 是可选能力；Docker Server 的基础自托管功能不依赖 Hermes Link Cloud。
