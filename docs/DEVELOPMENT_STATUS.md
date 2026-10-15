# Development status

## 已实现

- 命令解析：`/help`、`/pair`、`/bind`、`SGWCMAID...`、`/wechat`、
  `/b50`、`/status`、`/unbind`。
- 群聊敏感凭据默认拒绝。
- `Import-Token` 验证与 Fernet 加密存储。
- 水鱼完整成绩、成绩写入、公开 B50 三个 HTTP 端点适配器。
- SQLite 开发存储、任务状态机、单用户锁、HMAC 幂等摘要。
- 一次性提交 nonce 与受内部令牌保护的 FastAPI 入口。
- 项目自有 B50 五列模板；曲绘、曲目元数据从水鱼公开接口按需读取，失败时使用占位图。
- 离线 Fake 端到端演示和自动测试。
- 锁定 `nonebot-adapter-qq==1.7.2` 与 `nonebot2==2.5.0` 的 QQ WebSocket 入口。
- 只启用私聊与群聊 @ 消息 intent；频道、审核、成员等无关 intent 明确关闭。
- QQ 群聊与私聊事件映射、一次性配对码、完整命令转发和 B50 图片发送。
- 配对码只保存 HMAC 摘要；OpenID 只保存 HMAC 化内部身份键。
- 真实 QQ WebSocket 中的群聊与私聊 `/help` 已分别验证成功。
- 可选 `maimai-py==1.5.2` 与 `maimai-ffi==0.7.1` 机台适配器，支持
  `SGWCMAID...` 基础成绩读取和水鱼热更新。
- 华立未返回 FC/FS 时保留水鱼已有值；PC 缺失时明确显示 `—`。
- Windows 微信 OAuth 页面的一次性脱敏采集工具；只观测精确域名的
  HTTP 回调，采集后恢复原 Clash 配置。
- 华立成绩 HTML 解析器：列表页读取达成率、DX 分、FC、FS、
  评级、难度和 SD/DX 类型；详情页读取单谱面 PC 次数与 DX 星数。
- 2026-09-23 真实脱敏样本验证了 5 个成绩列表页和 5 个详情页；
  样本中共解析 1274 条已游玩成绩和 8 个详情谱面。
- 本机单用户微信 OAuth 闭环：QQ 私聊一次性任务、只监听
  `127.0.0.1` 的受保护 API、五难度成绩上传、当前 B50 详情定向采集。
- OAuth 回传令牌只保存 HMAC 摘要；Cookie 和 OAuth 参数不落盘。
- B50 渲染会按精确的曲名、SD/DX 类型和难度序号合并本地 PC/网页星数。
- 主项目自动测试 65 项、微信采集器测试 8 项全部通过；两部分
  源码与测试文件均通过 Python 字节码编译检查。

## 必须补充证据后实现

1. 将当前本机单用户 OAuth 助手扩展为多用户公开服务；远程用户
   需要各自的 Windows 微信助手或得到华立支持的公网回调方案。
2. 二维码玩家与水鱼账号没有可由当前接口直接核对的同一身份字段。
3. 使用项目方专用测试账户完成新 OAuth 闭环的真实上传和 B50 脱敏验收。
4. `maimai-ffi` 闭源 wheel 的许可证和供应链审批。
5. PostgreSQL、Redis、生产 KMS、HTTPS 和完整 SBOM。

## 生产禁用项

- `UnavailableArcadeScoreProvider` 仍是默认成绩采集器；管理员必须安装 `[arcade]`
  依赖并显式设置 `NALMAI_ARCADE_PROVIDER=maimai_py` 才会访问机台服务。
- `UnconfiguredQQEventBridge` 仅作为旧接口保护保留，QQ 插件不再使用它。
- SGWC 凭据不写数据库、不写普通日志；只在当前私聊请求内存中使用。
- SGWC 与微信 OAuth 是两种不同会话；只提交 SGWC 时不会从微信网页
  补出新 FC、FS 或 PC。
- QQ 原始事件采集默认关闭，且凭据标记会阻止原始文件写盘。
- B50 隐私 403 时不会自行推测 B35/B15 算法。
