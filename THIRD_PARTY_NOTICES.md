# Third-party notices

正式引入依赖时必须记录：项目名称、仓库地址、锁定版本或 commit SHA、许可证、修改情况、包文件名与 SHA-256。

当前基础工程只声明 Python 包依赖；最终锁文件和 SBOM 应在目标部署平台完成安装后生成。

## QQ 接入直接依赖

- NoneBot2 2.5.0，https://github.com/nonebot/nonebot2 ，MIT License，未修改。
- NoneBot QQ Adapter 1.7.2，https://github.com/nonebot/adapter-qq ，MIT License，未修改。

上述版本在 `pyproject.toml` 中锁定。当前受限开发环境未获准联网下载 wheel，
因此目标 Windows/Python 3.12 环境安装后，仍须补录 wheel 文件名、SHA-256，
并重新生成 `requirements.lock` 与 `sbom.cdx.json`。

不得复制没有明确许可证的仓库代码、图片、字体、曲绘或模板资源。

## 可选机台成绩依赖

- `TrueRou/maimai.py` / `maimai-py` 1.5.2，
  https://github.com/TrueRou/maimai.py ，作为未修改的 Python 包依赖调用。
  仓库根目录 `LICENSE` 为 Apache-2.0，但 `pyproject.toml` 的许可证字段写为
  MIT；Nalmai 不复制其源码，发布前仍应要求上游澄清元数据差异。
- `maimai-ffi` 0.7.1，https://pypi.org/project/maimai-ffi/ ，
  仅由 `maimai-py` 的机台适配器按需使用。该包只分发平台二进制 wheel，
  机台协议实现不开源；Nalmai 不打包或反编译该 wheel，管理员必须显式安装
  `[arcade]` 可选依赖并启用 `NALMAI_ARCADE_PROVIDER=maimai_py`。

当前 `ArcadeProvider` 源码明确把 FC、FS、play_count 设为 `None`。Nalmai 对
SGWC 路线缺失值不进行推测，并在上传时保留水鱼已有 FC/FS。独立的全开源
微信 OAuth 网页路线能够解析这些网页字段，但不能由 SGWC 凭据替代。

## Windows 微信采集器直接依赖

以下依赖仅安装在 `.venv-wechat/`，不进入 Nalmai QQ 机器人的 `.venv/`：

- `mitmproxy` 12.1.1，https://github.com/mitmproxy/mitmproxy ，MIT License，
  未修改；作为 Clash 精确单域名规则的本机 HTTP 接收端。
- `httpx` 0.28.1，https://github.com/encode/httpx ，BSD-3-Clause License，
  未修改；用于 OAuth 会话和只读成绩页面请求。
- `lxml` 6.1.3，https://github.com/lxml/lxml ，BSD-3-Clause License，
  未修改；用于提取成绩卡片、读取表单声明和生成脱敏 HTML。

微信 OAuth 交互流程依据 `TrueRou/maimai.py` 的 MIT 示例
`examples/proxy_updater` 重新实现。Nalmai 采集器不导入 `maimai-py`，因此不会
把闭源 `maimai-ffi` 带入全开源采集环境。

## B50 设计参考

- `Shio796/maimai-b50-image-generator`，
  https://github.com/Shio796/maimai-b50-image-generator ，MIT License。
  Nalmai 只研究其信息层级与水鱼公开数据使用方式；渲染代码重新实现，未复制
  该仓库需要另行下载的游戏 UI、字体、头像、姓名框或背景素材。`Nalmai
  Aurora` 的渐变、柔光、网格、分区底板和卡片阴影均由本项目代码绘制。
- 曲绘由水鱼文档公开的 `/covers/{cover_id}.png` 接口按需读取并仅作 B50 展示，
  失败时依次回退到 AWMC 与 SaltMeta 的公开曲绘接口，并缓存到本机；三个来源都
  无法取得时使用 Nalmai 自有占位图。Nalmai 不分发这些曲绘文件。
- B50 的 SD/DX、评级、FC/FS 状态图标来自用户本人授权会话所返回页面中明确
  引用的华立公开静态资源路径，并仅用于本机成绩图渲染。素材权利归原权利人，
  本项目不主张其许可权，也不将其作为可再分发的自由素材。
- 头像、姓名框、背景框与搭档图片只允许由机器人管理员通过本人授权会话同步
  到本机共享缓存；缓存的 `manifest.json` 保存来源路径并明确写入
  `redistribution_granted: false`。这些图片不纳入 Nalmai 源码、插件压缩包或
  MIT 许可范围，公开发布项目时必须排除共享缓存目录。
- `Resource Han Rounded CN Bold` 0.990，
  https://github.com/CyanoHao/Resource-Han-Rounded ，SIL Open Font License 1.1。
  未修改；文件 `ResourceHanRoundedCN-Bold.ttf` 的 SHA-256 为
  `f713907a21a10701cd68a7ce3e345ccdce46c789e1809d65ace54e095d7107c3`。
  许可证随字体保存在 `src/nalmai/assets/fonts/OFL-License.txt`。

## 仅研究、未引入

- `XiaoLan9999/astrbot_plugin_maimai_updater`，
  https://github.com/XiaoLan9999/astrbot_plugin_maimai_updater 。截至本次核验，
  仓库根目录没有明确许可证文件，且官方成绩链路依赖单独的运行资源。
  Nalmai 只参考其公开命令流程和测试目标，不复制代码、协议实现或运行资源，
  也不把它声明为依赖。
