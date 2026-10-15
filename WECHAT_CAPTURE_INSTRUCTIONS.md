# Windows 微信采集操作

该工具不使用 Edge，也不要求复制 Cookie、SGWC 或微信授权参数。

## 首次安装

在 Nalmai 项目目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_wechat_capture.ps1
```

## 每次采集

1. 保持 Nalmai QQ 机器人运行。
2. 在 QQ 私聊 Nalmai 发送 `/wechat`，确认返回“授权任务已创建”。
3. 启动并登录 Windows 微信。
4. 打开“以管理员身份运行”的 PowerShell。
5. 进入 Nalmai 项目目录并运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_wechat_capture.ps1
```

6. 先打开微信“文件传输助手”并点进输入框。
7. 回到 PowerShell，看到“采集器已就绪”后按一次 `Enter`。
8. 立即回微信按 `Ctrl+V`，发送并点击刚生成的链接。
9. 页面显示“授权已由 Nalmai 本机采集器接收”后，返回 PowerShell。
10. 程序会上传水鱼、保存当前 B50 的 PC/网页星数、恢复 Clash
    原配置，并显示 `nalmai-wechat-capture-*.zip` 路径。
11. 在 QQ 中发送 `/b50`。

授权链接默认只等待 180 秒；超时后必须重新运行，不要重复使用旧链接。

不要提供 `.env`、SGWC、Cookie、授权链接、HAR 或 `private` 目录文件。

该流程要求 Clash Verge 正在运行。脚本只临时转发
`tgk-wcaime.wahlap.com:80`，结束后恢复原配置。
