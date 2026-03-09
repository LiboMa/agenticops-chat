# Slack Dual-Bot Setup Template
# ops-bot-slack (接收) + alert-bot-slack (发送)
# Channel: #C0AK72GGX3Q

---

## 📋 总览

| 项目 | ops-bot-slack | alert-bot-slack |
|------|--------------|----------------|
| **职责** | 接收消息、监听指令 | 发送告警消息 |
| **方向** | ⬇️ 接收 (Inbound) | ⬆️ 发送 (Outbound) |
| **Token 类型** | Bot Token (`xoxb-`) | Bot Token (`xoxb-`) |
| **需要 Events** | ✅ 是 | ❌ 否 |
| **需要 Socket Mode** | 推荐 (无需公网) | ❌ 否 |

---

## 🤖 Bot 1: ops-bot-slack (接收消息)

### 创建步骤
1. https://api.slack.com/apps → **Create New App** → From scratch
2. App Name: `ops-bot-slack`
3. Workspace: 选择当前 workspace

### Bot Token Scopes (OAuth & Permissions)
```
app_mentions:read     # 接收 @ops-bot 提及
channels:history      # 读取频道消息历史
channels:read         # 列出/查看频道信息
chat:write            # 回复消息（确认收到等）
groups:history        # 读取私有频道消息
im:history            # 读取 DM
reactions:read        # 读取 emoji 反应
users:read            # 查看用户信息
```

### Event Subscriptions
开启 **Event Subscriptions**，订阅以下 Bot Events:
```
message.channels      # 公开频道新消息
message.groups        # 私有频道新消息
app_mention           # @ops-bot 提及
reaction_added        # emoji 反应（可选，用于确认/审批）
```

### Socket Mode (推荐)
- 左侧 **Socket Mode** → Enable
- 生成 App-Level Token (`xapp-...`)，名称: `ops-bot-socket`
- Scope: `connections:write`
- ✅ 无需公网暴露，适合内部服务

### 安装
- **Install to Workspace** → Allow
- 复制 Bot Token: `xoxb-...`
- 复制 App Token: `xapp-...` (Socket Mode)

### 加入频道
```
/invite @ops-bot-slack
```
在 #C0AK72GGX3Q 频道中执行

---

## 🚨 Bot 2: alert-bot-slack (发送告警)

### 创建步骤
1. https://api.slack.com/apps → **Create New App** → From scratch
2. App Name: `alert-bot-slack`
3. Workspace: 选择当前 workspace

### Bot Token Scopes (OAuth & Permissions)
```
chat:write            # 发送消息（核心）
chat:write.customize  # 自定义 bot 名称/头像发消息
files:write           # 上传文件/图片（告警截图等）
channels:read         # 查看频道信息
```

### 不需要 Event Subscriptions
alert-bot 只发不收，无需监听事件。

### 不需要 Socket Mode
纯 HTTP API 调用即可。

### 安装
- **Install to Workspace** → Allow
- 复制 Bot Token: `xoxb-...`

### 加入频道
```
/invite @alert-bot-slack
```
在 #C0AK72GGX3Q 频道中执行

---

## 🔑 Token 汇总 (创建后填写)

```bash
# ops-bot-slack
export OPS_BOT_TOKEN="xoxb-..."           # Bot Token
export OPS_BOT_APP_TOKEN="xapp-..."       # App Token (Socket Mode)
export OPS_BOT_SIGNING_SECRET="..."       # Signing Secret

# alert-bot-slack  
export ALERT_BOT_TOKEN="xoxb-..."         # Bot Token
export ALERT_BOT_SIGNING_SECRET="..."     # Signing Secret

# 共用
export SLACK_CHANNEL="C0AK72GGX3Q"        # 工作频道
```

---

## 📦 对接代码模版

### alert-bot-slack 发送告警 (Python)
```python
import os, requests

ALERT_TOKEN = os.environ["ALERT_BOT_TOKEN"]
CHANNEL = os.environ.get("SLACK_CHANNEL", "C0AK72GGX3Q")

def send_alert(title, detail, severity="warning"):
    """发送格式化告警到频道"""
    color_map = {"critical": "#FF0000", "warning": "#FFA500", "info": "#36A64F"}
    
    requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {ALERT_TOKEN}"},
        json={
            "channel": CHANNEL,
            "attachments": [{
                "color": color_map.get(severity, "#FFA500"),
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {title}"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
                    {"type": "context", "elements": [
                        {"type": "mrkdwn", "text": f"Severity: *{severity}* | Source: alert-bot-slack"}
                    ]}
                ]
            }]
        }
    )

# 使用示例
send_alert(
    "EC2 CPU > 90%", 
    "Instance `i-0abc123` CPU 持续 >90% 超过 5 分钟\nRegion: ap-southeast-1",
    severity="critical"
)
```

### ops-bot-slack 接收消息 (Python + Socket Mode)
```python
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

app = App(token=os.environ["OPS_BOT_TOKEN"])

@app.event("message")
def handle_message(event, say):
    """处理频道消息"""
    text = event.get("text", "")
    user = event.get("user", "")
    channel = event.get("channel", "")
    
    # 只处理工作频道的消息
    if channel == os.environ.get("SLACK_CHANNEL", "C0AK72GGX3Q"):
        print(f"[ops-bot] Received from {user}: {text}")
        # 转发给下游处理系统
        process_command(text, user, channel)

@app.event("app_mention")
def handle_mention(event, say):
    """处理 @ops-bot 提及"""
    text = event.get("text", "")
    say(f"✅ 收到指令，正在处理: {text}")

def process_command(text, user, channel):
    """下游处理逻辑"""
    # TODO: 对接你的业务系统
    pass

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["OPS_BOT_APP_TOKEN"])
    handler.start()
```

### 依赖安装
```bash
pip install slack-bolt slack-sdk requests
```

---

## ✅ 创建 Checklist

### ops-bot-slack
- [ ] Create App (api.slack.com/apps)
- [ ] 添加 Bot Scopes: app_mentions:read, channels:history, channels:read, chat:write, groups:history
- [ ] Enable Event Subscriptions: message.channels, app_mention
- [ ] Enable Socket Mode + 生成 App Token
- [ ] Install to Workspace
- [ ] 复制 Bot Token (`xoxb-`)
- [ ] 复制 App Token (`xapp-`)
- [ ] `/invite @ops-bot-slack` 到 #C0AK72GGX3Q
- [ ] 测试: 在频道 @ops-bot-slack 看是否收到事件

### alert-bot-slack
- [ ] Create App (api.slack.com/apps)
- [ ] 添加 Bot Scopes: chat:write, chat:write.customize, files:write, channels:read
- [ ] Install to Workspace
- [ ] 复制 Bot Token (`xoxb-`)
- [ ] `/invite @alert-bot-slack` 到 #C0AK72GGX3Q
- [ ] 测试: `curl -X POST https://slack.com/api/chat.postMessage -H "Authorization: Bearer xoxb-..." -H "Content-Type: application/json" -d '{"channel":"C0AK72GGX3Q","text":"🚨 Test alert"}'`

---

## 🔒 安全建议

1. **Token 分离** — 两个 bot 各自的 token 独立管理，泄露一个不影响另一个
2. **最小权限** — ops-bot 不需要 files:write，alert-bot 不需要 events
3. **Signing Secret 验签** — ops-bot 收到的每个请求都验证签名
4. **环境变量** — 不要硬编码 token，用 `.env` 或密钥管理服务
5. **Audit** — 定期检查 bot token 的使用情况
