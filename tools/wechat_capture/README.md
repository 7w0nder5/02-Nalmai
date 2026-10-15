# Nalmai Windows 微信脱敏采集器

本工具是 Nalmai 本机单用户微信 OAuth 更新助手。它不是常驻代理；
只在 QQ 私聊 `/wechat` 创建一次性任务后运行。

## 安全边界

- 运行脚本只向 Clash Verge 临时加入一条规则，将
  `tgk-wcaime.wahlap.com:80` 转发到 `127.0.0.1:8080`。
- 不把 Windows 搜索或 Clash 自己的 `msedgewebview2.exe` 纳入捕获范围。
- 应用层只处理 `tgk-wcaime.wahlap.com` 的 OAuth 回调域名与固定路径。
- 其他 HTTP 请求不记录、不保存，并由代理正常转发。
- 不安装 mitmproxy CA，不解密微信 HTTPS 流量。
- OAuth 参数和 Cookie 只保存在进程内存中，完成或失败后随进程退出。
- 与 QQ 用户的关联使用 5 分钟一次性任务；回传令牌只保存 HMAC 摘要。
- 回传 API 只监听 `127.0.0.1`，并使用 `.env` 中的内部令牌领取任务。
- 不写原始 HTTP 请求、HAR、Cookie、OAuth 参数或原始 HTML。
- 输出只包含成绩卡片、脱敏详情 HTML 与不含身份信息的清单。
- 每次启动只接受一次授权，默认 180 秒超时后退出。

## 使用

先在 Windows 微信中完成登录。首次使用，在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_wechat_capture.ps1
```

每次更新前，先保持 Nalmai QQ Bot 运行并在私聊发送 `/wechat`。然后
打开“以管理员身份运行”的 PowerShell，在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_wechat_capture.ps1
```

程序会先领取一次性任务。显示“采集器已就绪”后，先准备好
Windows 微信“文件传输助手”，再回到
PowerShell 按 Enter。程序此时才生成短时授权链接并复制到剪贴板；请立即粘贴、
发送并点击。网页提示已经收到授权后，返回 PowerShell 等待压缩包路径出现。

授权后程序会上传五个难度的已游玩成绩，再只读取当前 B50 需要的
详情页并回传 PC/网页星数。脚本在结束时恢复 Clash 原配置并删除
临时配置文件。

只分享最终的 `nalmai-wechat-capture-*.zip`。如果失败，不要截图或复制完整
授权链接；重新运行采集器生成新链接即可。

## 输出

- `score-list-diff-0..4.sanitized.html`：五个难度的成绩卡片。
- `music-detail-N.sanitized.html`：当前 B50 所需曲目的去重详情页面。
- `manifest.json`：文件数量、卡片数量和采集格式版本。

所有输出都位于 `data/wechat-capture/`，该目录已加入 `.gitignore`。
