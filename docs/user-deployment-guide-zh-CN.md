# Hermes Link Server 用户部署手册

> 适用版本：Hermes Link Server 1.0.0、Hermes Link Protocol v1。  
> 原则：**自托管是基础模式；Cloud 可选；Hermes Link Server 是 App 与 Hermes Agent 的兼容边界。**

本手册部署的是 `hermes-link-server`，不是 Hermes Agent、不是 Cloud
Admin，也不需要 Huawei Push 凭据。完成后，HarmonyOS App 只访问 Server 的
公开 HTTPS 接口；Server 再通过本机回环访问 Hermes Agent。

## 1. 部署后的拓扑

```text
Hermes Link App
        │ HTTPS :443
        ▼
Nginx 或 Caddy
        │ HTTP 127.0.0.1:8765
        ▼
Hermes Link Server Bridge
        │ HTTP 127.0.0.1:8642
        ▼
Hermes Agent
```

Cloud 未启用时，聊天、Session、任务、历史和 DIRECT 通知照常可用。

## 2. 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux，建议 systemd 发行版（Ubuntu 22.04+/Debian 12+/Rocky 9+） |
| Python | 3.11 或更高 |
| 网络 | 一个可被手机访问的 HTTPS 域名；Server 与 Agent 位于同一主机或受控本机网络命名空间 |
| TLS | Nginx 或 Caddy 终止 TLS，必须是受手机信任的有效证书 |
| Hermes Agent | 已运行，且只监听回环地址，例如 `127.0.0.1:8642` |
| 存储 | Server 状态目录可写；至少预留 1 GB 供日志和 SQLite pairing 数据库 |
| 权限 | `hermes-link` 服务用户仅可写自己的状态目录；对 Hermes 元数据仅授予需要的只读权限 |

不要将 Hermes Agent、SQLite 文件或端口 `8765` 暴露到公网。

## 3. 端口规划与防火墙

| 端口 | 监听位置 | 用途 | 公网开放 |
| --- | --- | --- | --- |
| 443/TCP | Nginx/Caddy | App 的 HTTPS Hermes Link Protocol v1 | 是 |
| 8765/TCP | `127.0.0.1` | Hermes Link Bridge | 否 |
| 8642/TCP | `127.0.0.1` | Hermes Agent（示例） | 否 |
| 22/TCP | 视运维策略 | SSH 运维 | 仅受限来源 |

若已有反向代理占用 443，可按现有站点增加 `/hermes-link/v1/` location；不要将 8765 映射到 Docker host 或安全组公网规则。

## 4. 安装

以下以 root 或具备 sudo 的管理员为例。仓库可以通过受控 Git clone、制品仓库或离线复制放到 `/opt/hermes-link-server`；先审查代码和锁定版本。

```bash
sudo useradd --system --home /var/lib/hermes-link-server --create-home --shell /usr/sbin/nologin hermes-link
sudo install -d -o hermes-link -g hermes-link -m 0700 /var/lib/hermes-link-server
sudo python3 -m venv /opt/hermes-link-server/.venv
sudo /opt/hermes-link-server/.venv/bin/pip install /opt/hermes-link-server
```

在安装目录运行发布前门禁：

```bash
cd /opt/hermes-link-server
/opt/hermes-link-server/.venv/bin/python -m unittest discover -s tests -t . -p 'test_*.py'
/opt/hermes-link-server/.venv/bin/python scripts/architecture_gate.py
/opt/hermes-link-server/.venv/bin/python scripts/secret_scan.py
```

## 5. Server 环境文件

复制 [`deploy/systemd/hermes-link-server.env.example`](../deploy/systemd/hermes-link-server.env.example)
到 `/etc/hermes-link-server/server.env`，并限制权限：

```bash
sudo install -d -m 0750 /etc/hermes-link-server
sudo install -m 0600 -o root -g hermes-link \
  /opt/hermes-link-server/deploy/systemd/hermes-link-server.env.example \
  /etc/hermes-link-server/server.env
sudoedit /etc/hermes-link-server/server.env
```

需要配置的项目：

- `HERMES_AGENT_BASE_URL`：仅回环地址，例如 `http://127.0.0.1:8642`。
- `HERMES_LINK_MOBILE_API_TOKEN`：由安装器自动生成并仅保存在 `/etc/hermes-link-server/internal-agent.env`（`0600`）。不要手动获取、填写、打印或复制上游 Token。
- `HERMES_LINK_PAIRING_DB`：建议 `/var/lib/hermes-link-server/pairing.db`。
- `HERMES_HOME`：供受控元数据读取的 Hermes 数据目录；不要把完整 Home 写入 Git。
- `hermesVersion` 由 Server 从已认证的 Hermes Agent 运行时健康接口读取，仅作诊断展示；App 不以它决定功能。

环境文件、pairing 数据库、私钥及 Agent Token 都不可复制到 App、二维码、日志或 Git。

## 6. 配置 systemd

```bash
sudo cp /opt/hermes-link-server/deploy/systemd/hermes-link-server.service \
  /etc/systemd/system/hermes-link-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-link-server
sudo systemctl status hermes-link-server --no-pager
```

Bridge 只应监听 `127.0.0.1:8765`。本机健康检查：

```bash
curl --fail http://127.0.0.1:8765/health
```

失败时优先查看状态和脱敏日志，不要把环境文件内容粘贴到工单：

```bash
sudo journalctl -u hermes-link-server -n 100 --no-pager
```

## 7. 配置 HTTPS 反向代理

### Nginx

将 [`deploy/nginx/hermes-link.conf.example`](../deploy/nginx/hermes-link.conf.example)
中的 location 放入已经配置好 `listen 443 ssl` 的目标站点。示例只代理
`/hermes-link/v1/` 到 `127.0.0.1:8765`；它**不**通过 Agent 的 `/v1/models`
作二次鉴权，因为一次性配对端点必须由 Server 自己处理。

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://link.example.com/hermes-link/v1/server-info
```

### Caddy

使用 [`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example)，将
域名替换为自己的域名。Caddy 示例现在代理 `127.0.0.1:8765`。确认 DNS 已指向
服务器且证书签发成功后：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

公网只允许 HTTPS。自签名证书、HTTP URL、URL 中嵌入用户名/密码都会被 App 拒绝。

## 8. 生成二维码并在 App 配对

二维码只含短期、一次性配对 URL；不含 Agent Token、设备 Token、私钥或 Cloud
凭据。默认有效期 600 秒，可设为 30–3600 秒。

在 Server 主机中使用安全密钥系统或短期、权限为 `0600` 的运行时环境文件，向
配对命令使用安装器生成的 `/etc/hermes-link-server/internal-agent.env`；它与 Agent systemd drop-in 使用同一份内部凭据。
不要写进 shell 历史，也不要把值作为命令参数。由密钥系统在
`/run/hermes-link/pairing.env` 写入该变量后，以服务账户执行：

```bash
cd /opt/hermes-link-server
sudo -u hermes-link sh -c '
  set -a
  . /run/hermes-link/pairing.env
  set +a
  exec /opt/hermes-link-server/.venv/bin/python -m hermes_link.pairing.store \
    --base-url https://link.example.com \
    --profiles default,mobiletest \
    --ttl 600
'
```

命令只输出 `pairing_url` 和过期时间。将该 URL 使用你受信任的离线二维码工具显示为二维码；不要贴到公共聊天室、Issue 或截图中。然后在 App 的「我的 → 服务器 → 扫码配置」扫码。

扫码后 App 通过 `POST /hermes-link/v1/pairing` 交换一次性 code，取得受 Profile 范围限制的设备 Token 并写入平台安全存储。code 重复使用会收到 `pairing_used`，过期会收到 `pairing_expired`；两者都应重新生成二维码。

> `HERMES_MOBILE_API_TOKEN` 仅由命令读取，不会显示在输出中。`pairing.env` 还应包含 `HERMES_LINK_PAIRING_DB=/var/lib/hermes-link-server/pairing.db`。生产上应通过受限的临时环境导入方式注入，完成后由运维流程销毁该运行时密钥材料。

## 9. 配对和功能验收

1. App 顶部状态为“已连接”。
2. `GET /hermes-link/v1/server-info` 返回 `protocolVersion: 1` 和 feature flags。
3. App 中 Profile、模型、Session 能加载；用已授权 Profile 新建一次普通聊天。
4. 检查另一个未授予的 Profile 被拒绝，而不是返回数据。
5. 只启用自托管模式时，聊天、历史、任务和 DIRECT 通知仍工作。
6. 可在 App 的服务器设置撤销当前设备；这只撤销该设备 Token，不影响其他设备。

不要用 Hermes Agent 版本号写 App 条件分支；功能由 `protocolVersion` 与 `features` 决定。

## 10. 可选 Cloud

Cloud 是可选通知平台，不是 Server 的部署前提。启用前先完成自托管验收，再按 Cloud Protocol v2 建立 Server 身份和绑定。Server 只发送允许的事件：

- `chat.completed`
- `job.completed`
- `job.failed`

不得上传完整聊天正文、Prompt、Agent 回复、Agent Token、登录凭据或私钥。Server 不访问 Cloud 数据库，也不导入 Cloud Python 模块。

## 11. 常见故障

| 现象 | 检查顺序 |
| --- | --- |
| App 连接失败 | 域名 DNS、443/TLS、Nginx/Caddy 路径、`/hermes-link/v1/server-info`、Bridge `/health` |
| 扫码后配对失败 | URL 是否 HTTPS、是否过期/已用、反向代理是否转发 pairing 路径、pairing DB 是否可写 |
| 配对后 401 | 设备 Token 被撤销、Profile 不在二维码 `--profiles` 范围内、或 Server pairing DB 不是当前服务使用的路径 |
| 配对后 503 | 检查 Hermes Agent systemd drop-in 与 `/etc/hermes-link-server/internal-agent.env` 是否存在、权限是否为 `0600`，然后用 `bootstrap-hermes-agent-access.sh --rotate` 轮换；不要打印凭据 |
| 模型一直读取 | 检查 Profile scope、Agent loopback 连通性和 `/hermes-link/v1/profiles/<profile>/models/config`，而非修改 App 的 Agent 版本判断 |
| 长聊天中断 | 检查代理的 310 秒 read/send timeout、Bridge 日志及 Agent 服务状态 |

## 12. 升级、回滚与卸载

升级前备份 `/var/lib/hermes-link-server`，记录当前制品版本并运行测试。先停 Bridge，再替换 Server 包和虚拟环境，启动后复验 `/health`、`server-info` 和一台已配对设备。

回滚只恢复上一个 Server 包、虚拟环境和 systemd unit。**不要**通过删除 Hermes Agent 数据、撤销所有设备或修改 Cloud 绑定来“顺带回滚”。如需撤销设备，只在 App 或受控 Server 操作中撤销目标设备。
