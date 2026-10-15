# astrbot_plugin_nalmai

Nalmai 的 AstrBot + OneBot v11 接入插件。适用于个人 QQ 机器人，不依赖 QQ
开放平台企业开发者的“允许添加到任意群聊”权限。

## 功能

- 每个 QQ 用户独立、加密保存水鱼 Import-Token。
- 私聊提交 `SGWCMAID...` 后热更新水鱼成绩。
- 私聊或群聊生成 Nalmai B50 图片；`/nalmai b50` 与 `@机器人 b50` 输出一致。
- B50 优先使用发送者 QQ 头像，并显示已确认的官方 SD/DX、评级、FC/FS 图标。
- 管理员一次授权同步头像、姓名框、背景框和搭档收藏素材到插件数据目录，
  所有群友共享使用；素材不会打入插件发布包。
- B50 使用淡彩难度卡片、蓝暖双色分区和放大的核心成绩文字。
- 同一 QQ ID 直接贯通私聊与群聊，不再需要 `/pair`。
- 敏感绑定和更新指令强制私聊。
- 高消耗指令按用户冷却，并设置全局并发上限。

## 安装

将整个 `astrbot_plugin_nalmai` 文件夹复制到：

```text
<AstrBot>/data/plugins/astrbot_plugin_nalmai/
```

通过 AstrBot WebUI 上传插件压缩包时，AstrBot 会安装 `requirements.txt`。
如果依赖安装失败，在 WebUI 的“数据 → 日志 → 安装 Pip 库”中按错误信息
重新安装，然后重载插件。持久化数据自动写入：

```text
<AstrBot>/data/plugin_data/astrbot_plugin_nalmai/
```

不要删除其中的 `security.json`，否则已经保存的 Import-Token 将无法解密。
公共收藏素材保存在同目录下的 `shared_assets/`；删除后只会失去共享美术素材，
不会删除用户水鱼绑定，但需要管理员重新运行一次微信采集才能恢复。

## 指令

```text
/nalmai help
/nalmai bind <QQ号码> <Import-Token>    # 仅私聊
/nalmai update <SGWCMAID...>            # 仅私聊
/nalmai assetsync                        # 管理员私聊创建共享素材同步任务
/nalmai b50                              # 私聊或群聊
@机器人 b50                             # 与 /nalmai b50 完全相同
/nalmai status                           # 私聊或群聊
/nalmai unbind                           # 仅私聊
```

## 说明

插件结构参考了 AstrBot 官方插件文档及
`ZhiheZier/astrbot_plugin_maimaidx` 的功能组织方式，但没有复制该插件的代码或
美术素材。Nalmai B50 继续使用本项目自己的渲染器。

发布到 GitHub 或 AstrBot 市场前，需要由项目所有者填写 `metadata.yaml` 的
`repo`，并确定 Nalmai 自身的开源许可证。
