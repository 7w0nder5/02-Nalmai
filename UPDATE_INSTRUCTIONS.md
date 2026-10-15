# Nalmai v1.5 更新说明

## 更新前

1. 在正在运行 Nalmai 的 PowerShell 窗口按 `Ctrl+C` 停止机器人。
2. 不要删除或替换项目中的 `.env`、`.venv` 和 `data` 文件夹。

## 覆盖更新

将更新压缩包解压后，把其中全部文件复制到：

```text
C:\Users\Administrator\Desktop\ChatGPT项目\Nalmai
```

Windows 询问时选择“替换目标中的文件”。更新包不含 `.env`、`.venv` 和
`data`，因此不会覆盖现有密钥、QQ AppSecret、绑定数据库和事件记录。

## 安装新增机台依赖

在项目目录执行：

```powershell
.\.venv\Scripts\python -m pip install -e ".[qq,arcade,dev]"
```

然后用记事本打开现有 `.env`，新增以下两行。第二行没有代理时保持空值：

```text
NALMAI_ARCADE_PROVIDER=maimai_py
NALMAI_ARCADE_HTTP_PROXY=
NALMAI_LOCAL_API_PORT=8000
```

## 启动

```powershell
cd "C:\Users\Administrator\Desktop\ChatGPT项目\Nalmai"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m nalmai.qq_main
```

## 推荐验证顺序

```text
私聊：/help
群聊：@Nalmai /help
私聊：/status
私聊：/bind <QQ号码> <Import-Token>
私聊：发送当前仍有效的 SGWCMAID... 身份码
私聊：/wechat
本机管理员 PowerShell：执行 scripts\run_wechat_capture.ps1
私聊：/b50
私聊：/pair
目标群：@Nalmai /pair <8位配对码>
目标群：@Nalmai /status
目标群：@Nalmai /b50
```

`Import-Token` 只在机器人私聊中发送，不要发到群里或其他聊天。

## 当前限制

SGWC 机台路线只提供基础成绩，不提供新的 FC、FS、PC 次数。Nalmai 会保留
水鱼已有 FC/FS，PC 在 B50 中显示为 `—`，不会生成推测值。`maimai-ffi` 是
上游发布的闭源平台 wheel；不接受该依赖时不要启用 `maimai_py`。Windows
微信 OAuth 页面是独立的全开源路线，不能由 SGWC 凭据替代。
本机单用户版已可通过 `/wechat` 建立一次性关联，更新成绩并将
当前 B50 谱面的 PC/网页星数保存到本地数据库。
