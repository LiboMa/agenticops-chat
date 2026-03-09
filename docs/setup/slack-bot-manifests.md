# Slack App Bot 权限清单 (与 OpenClaw Bot 一致)
# 可直接用于 Slack App Manifest 导入

## 当前 OpenClaw Bot 权限 (共 16 个 scopes)

```
app_mentions:read    # 接收 @mention 事件
channels:history     # 读取公开频道消息历史
channels:read        # 列出/查看频道信息
chat:write           # 发送消息
commands             # 接收 slash commands
emoji:read           # 读取 emoji 列表
files:read           # 读取/下载文件
files:write          # 上传文件
groups:history       # 读取私有频道消息历史
im:history           # 读取 DM 消息历史
mpim:history         # 读取多人 DM 消息历史
pins:read            # 读取 pin 消息
pins:write           # Pin/Unpin 消息
reactions:read       # 读取 emoji 反应
reactions:write      # 添加 emoji 反应
users:read           # 读取用户信息
```

---

## Slack App Manifest (JSON 格式，可直接导入)

### ops-bot-slack Manifest
```json
{
  "display_information": {
    "name": "ops-bot-slack",
    "description": "AgenticOps 运维指令接收 Bot",
    "background_color": "#1a1a2e"
  },
  "features": {
    "bot_user": {
      "display_name": "ops-bot-slack",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "channels:history",
        "channels:read",
        "chat:write",
        "commands",
        "emoji:read",
        "files:read",
        "files:write",
        "groups:history",
        "im:history",
        "mpim:history",
        "pins:read",
        "pins:write",
        "reactions:read",
        "reactions:write",
        "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "app_mention",
        "message.channels",
        "message.groups",
        "reaction_added"
      ]
    },
    "interactivity": {
      "is_enabled": false
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true
  }
}
```

### alert-bot-slack Manifest
```json
{
  "display_information": {
    "name": "alert-bot-slack",
    "description": "AgenticOps 告警发送 Bot",
    "background_color": "#ff9900"
  },
  "features": {
    "bot_user": {
      "display_name": "alert-bot-slack",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "channels:read",
        "chat:write",
        "files:write",
        "reactions:write"
      ]
    }
  },
  "settings": {
    "interactivity": {
      "is_enabled": false
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": false
  }
}
```

---

## 导入方法

1. 打开 https://api.slack.com/apps
2. **Create New App** → **From an app manifest**
3. 选择 Workspace
4. 粘贴上面的 JSON manifest
5. Review → **Create**
6. **Install to Workspace**
7. 复制 Bot Token (`xoxb-...`)

ops-bot 额外步骤：
8. **Socket Mode** → Enable → Generate App Token (`xapp-...`)

---

## 两个 Bot 权限对比

| Scope | ops-bot | alert-bot | 说明 |
|-------|---------|-----------|------|
| app_mentions:read | ✅ | ❌ | 接收 @mention |
| channels:history | ✅ | ❌ | 读消息历史 |
| channels:read | ✅ | ✅ | 查看频道信息 |
| chat:write | ✅ | ✅ | 发送消息 |
| commands | ✅ | ❌ | Slash commands |
| emoji:read | ✅ | ❌ | Emoji 列表 |
| files:read | ✅ | ❌ | 下载文件 |
| files:write | ✅ | ✅ | 上传文件 |
| groups:history | ✅ | ❌ | 私有频道 |
| im:history | ✅ | ❌ | DM |
| mpim:history | ✅ | ❌ | 多人 DM |
| pins:read | ✅ | ❌ | 读 Pin |
| pins:write | ✅ | ❌ | 写 Pin |
| reactions:read | ✅ | ❌ | 读反应 |
| reactions:write | ✅ | ✅ | 加反应 |
| users:read | ✅ | ❌ | 用户信息 |
| **总计** | **16** | **4** | |
