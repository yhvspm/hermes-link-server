# Hermes Link Server 用户部署手册

> 适用版本：Hermes Link Server 1.0.2、Hermes Link Protocol v1。
> 原则：自托管是基础模式；Cloud 可选；Server 是 App 与 Hermes Agent 的兼容边界。

## 1. 默认拓扑：直接 HTTP/IP

```text
Hermes Link App
        │ HTTP :18766
        ▼
Hermes Link Server
        │ HTTP 127.0.0.1:8642 或 127.0.0.1:8080
        ▼
Hermes Agent
```

默认安装不集成 Caddy、Nginx、证书申请、域名解析或端口 `80` 校验。手机可通过
IP 地址直接访问 Server；Agent 始终只应监听本机回环地址。

## 2. 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | 标准安装器支持 Ubuntu 22.04+，包括 25.10、26.04 |
| Hermes Agent | 已在本机正常运行，Provider 配置已完成 |
| Docker | Docker Engine 与 Compose v2（当前标准安装器会检查） |
| 网络 | 手机可访问的 IP/域名和 TCP `1024..65535` 端口 |
| 端口 | 例如 `18766`；不要开放 Agent 的 `8642`/`8080` |

直接 HTTP 不加密。App API 和一次性配对兑换都通过该链路传输设备 Token，因此**仅
限可信 LAN、VPN 或受控网络**，不要裸露到通用公网。

## 3. 安装

在已运行 Hermes 的 Ubuntu 主机执行这一条命令：

```bash
curl -fsSL https://github.com/yhvspm/hermes-link-server/releases/download/v1.0.2/hermes-link-server-install.sh | \
  sudo bash -s -- --host 192.168.1.10 --public-port 18766
```

发布环境应先核对 Release 的完整性资产；本地候选版本则只能使用经审核的本地源码和镜像，
不能冒充已公开发布的不可变 Release。

安装器会：

1. 校验 Ubuntu、Docker、Hermes Agent 上下文；
2. 在 Server 侧生成专用内部凭据，不显示、不要求粘贴 Agent Token；
3. 自动发现有效 Hermes Profile 名称；
4. 在 `0.0.0.0:18766` 启动 Hermes Link Server；
5. 输出短期、一次性的 App 配对二维码。

如启用 UFW 或云安全组，请由主机管理员放行选定的 TCP 端口。安装器不会改防火墙。

## 4. App 添加 Hermes

安装成功后，打开 App：**设置 → 服务器 → 扫码配置**，扫描终端二维码即可。二维码
只含短期配对码，不包含 Hermes Agent Token、设备 Token、私钥或 Cloud 凭据。

也可手动输入地址，例如：

```text
http://192.168.1.10:18766
```

App 会把 HTTP 标记为“未加密”。Cloud Provider 仍只支持 HTTPS，不会因 Server
支持 HTTP 而降级。

## 5. 常用运维命令

```bash
sudo hermes-link status
sudo hermes-link doctor
sudo hermes-link pair
sudo hermes-link restart
sudo hermes-link update
```

`pair` 可为另一台手机生成新的短期二维码，不会撤销已有设备。`doctor` 只检查本机
健康、身份、Profile 和可选 Cloud，不会泄露 Agent 凭据。

## 6. 可选的用户自管 HTTPS

如果确实需要公网 HTTPS 域名，域名、证书、Caddy/Nginx/其他反向代理均由用户自行
申请和维护；Hermes Link Server 不读取私钥、不申请证书、不占用 `80`。示例：

```bash
sudo bash hermes-link-server-install.sh \
  --public-url https://hermes.example.com:24443 \
  --listen-host 127.0.0.1 \
  --listen-port 18766
```

把自管代理的 `/hermes-link/v1/*` 转发到 `http://127.0.0.1:18766`，保留
`Authorization`，并关闭流式响应缓冲。二维码会使用 `--public-url` 指定的 HTTPS
地址。详见 [高级部署](advanced-deployment.md)。

## 7. Cloud（可选）

Cloud 不是 Server 部署前提。不开启 Cloud 时，聊天、Session、任务、历史和 DIRECT
通知仍可工作。若启用 Cloud，Server 只经公开 Cloud Protocol 发送受限事件；不要把
完整聊天正文、Prompt、Token、私钥或 Provider 凭据上传到 Cloud。

## 8. 排障

| 现象 | 检查顺序 |
| --- | --- |
| App 无法连接 | IP/端口、手机网络、UFW/安全组、`sudo hermes-link doctor` |
| 扫码配对失败 | 二维码是否过期/已用、App URL 是否可达、Server pairing DB 是否可写 |
| 配对后 503 | Hermes Agent 服务、内部凭据权限、Server 本机健康 |
| 外部 HTTPS 失败 | 用户自管 DNS、证书、代理路径和流式转发；不属于安装器自动处理范围 |

不要将 `.env`、`internal-agent.env`、二维码截图、Docker 日志或私钥提交到 Git、
Issue 或聊天记录中。
