# 重置密码时可以自己输入新密码


## Context

**你说的**：「优化重置密码：用户可以输入新密码，不只是随机生成。」问过之后你定了：

- **谁来输入**：管理员在「用户管理」（`/app/users`）里重置时。新建用户仍然随机生成。
- **规则**：至少 8 个字符。
- **自己改密码**也用同一条规则。

**现在的样子**（读代码看到的）：

- 重置只有一种：`POST /api/users/{id}/reset-password` 由服务端生成随机密码（`services/user_admin.reset_password`，`secrets.token_urlsafe(12)`），页面上的确认框点「重置」之后，一次性显示这个密码。
- 服务端对密码**一条规则都没有**：自己改密码的接口 `PUT /api/users/me/password` 连空字符串都收。
- **页面上没有「改自己的密码」的地方**，只有这个接口。

**做完之后**：

- 管理员重置密码时，可以选「随机生成」（照旧），也可以「自己设定」（输两遍）。
- 服务端检查规则，不合规就拒绝，什么都不改。
- 自己改密码的接口也检查同一条规则。

## 规则（服务端检查，页面上照样提示）

一个新密码必须满足：

- 8–128 个字符；
- 不能全是空格；
- 不含控制字符。

已经存在的密码不受影响：规则只管新设的密码。

## 改动

### 后端

1. `auth/service.py`：新增 `password_problem(password) -> Optional[str]`，返回不合规的原因代码，合规返回 `None`。放在 `hash_password` 旁边，两处共用。
2. `services/user_admin.reset_password(user_id, *, caller, keep_token_hash=None, password: Optional[str] = None) -> Optional[str]`：
   - 给了 `password`：先检查规则，不合规抛 `UserAdminError(422, "weak_password", …)`，库里什么都不动；合规就存它，返回 `None`（管理员自己知道这个密码，不回传）。
   - 没给：照旧生成并返回。
   - 两种都照旧：结束这个用户的会话（重置自己时保留当前这一个）；写一行 `user.reset_password` 审计，多记 `{"method": "typed"|"generated"}`，从不记密码。
3. `web/routers/users.py` 的重置接口：请求体可选 `{"password": "..."}`（`PasswordResetRequest`，`max_length` 1024，挡住超大的请求体）。返回 `{"password": <生成的> | null, "generated": true|false}`，`PasswordResetResponse.password` 改成可空。
4. `web/routers/auth.py` 的 `PUT /api/users/me/password`：先检查新密码的规则，不合规返回 422 `{detail, code: "weak_password"}`；再核对旧密码，照旧。

### 前端（`web/frontend/src`）

1. `lib/users.ts`：
   - `passwordProblem(pw)`：和服务端同一条规则（页面提示用，服务端才是关）；
   - `resetPayload(mode, pw, confirm)`：两遍不一致、或不合规时返回原因，否则返回请求体。
2. `components/users/UserDialogs.tsx`：新增 `ResetPasswordDialog`，代替现在那个确认框。用现成的 `ModalFrame`，滑入动画和 ESC 关闭都有。
   - 两个选项：「随机生成」（默认）、「自己设定」。
   - 选「自己设定」时出现两个密码框（新密码、再输一遍），可以切换显示 / 隐藏，下面写着规则。不满足规则或两遍不一致时，「重置」按钮不能点，并写明原因。
   - 照旧写明「他已登录的浏览器会被登出」；重置自己时写「你在这里保持登录」。
3. `pages/Users.tsx`：
   - 点重置打开这个对话框；
   - 随机生成成功：照旧弹出一次性显示密码的对话框；
   - 自己设定成功：页面上方出一行提示「已为 {email} 设定新密码；他已登录的浏览器已登出」，不显示密码；
   - 服务端的 `weak_password`：在对话框里写明原因。
4. `hooks/useUsers.ts`：重置的请求带上可选的 `password`。
5. `locales/en.json`、`locales/zh.json`：新文案。

新界面（`/app/new`）里的用户管理用的就是这个页面，不用另改。

## 六个面

| 面 | 这一次 |
|---|---|
| CLI | 非目标：命令行没有重置密码的命令（`aiops users` 只有 create / list / disable），不加 |
| Web API | **做**：重置接口可以带 `password`；自己改密码的接口检查规则 |
| Web UI | **做**：用户管理的重置对话框可以选「自己设定」。自己改密码：非目标——页面上本来就没有这个入口，只有接口；要加入口，另说 |
| Agent 工具 | 非目标：没有 agent 工具管用户 |
| 定时任务 | 非目标 |
| 通知 | 非目标 |

## 我替你定的（不同意就在批准时说）

1. **自己设定的密码不回传、不显示第二次**：管理员刚输过，回传等于多一个泄露的地方。
2. **不加「下次登录必须改密码」**：现在没有这个机制，加的话要改登录流程。
3. **密码的存法不改**：现在是加盐的 SHA-256，代码里自己注明「生产环境应该用 bcrypt」。换成 bcrypt 是另一件事，会影响所有已有的密码。

## 测试

**后端**：`tests/test_users_api.py` 加用例，先写、先看着它失败：

- 管理员带密码重置：存下的是这个密码，用它能登录、旧密码不能；返回里没有密码；这个用户的会话结束了。
- 不带密码：照旧生成、返回。
- 不合规的密码（7 个字符、全是空格、含控制字符、129 个字符）：422 `weak_password`，库里没变，会话没被结束，没写审计行。
- 审计行写了 `method`，没有密码。
- 非管理员、API Key：照旧被拒绝。
- 自己改密码：新密码不合规就 422，旧密码照样能用；合规照旧成功。

**前端**：`__tests__/users.test.ts` 加 `passwordProblem`、`resetPayload` 的用例。

**门禁**：

- 故意改错检查；
- 后端全量测试；
- 前端在 `/tmp` 的干净目录里 `npm ci`、`tsc`、`build`、`vitest`（本机 home 下的 `node_modules` 会让检查假通过）；
- 在预览上用浏览器走一遍：两种重置，加上不合规、两遍不一致。预览是白皮书会话在用的副本库，所以在另一个端口、用另一份临时库起一个，不碰 :8001。

## 文档

`docs/MVP-2.9.0-RELEASE.md` 加一节（N34）；`docs/WORKFLOW.md` 的用户账户一节写明两种重置和规则；CLAUDE.md 的 `auth/` 一行；两份 README 在 2.9.0 那一行的末尾各加一句（2.8.0 那一行是当时的记录，不改；也不动白皮书会话引用的那两句）。

## 和正在进行的重建的关系

开发机的重新扫描还在跑。这一项要部署到开发机时，等那边扫完、复原之后再部署，部署前照旧备份。
