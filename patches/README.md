# DeepSteam 本地补丁

这个目录记录对已安装程序做的本地修改，每个补丁一个子目录，都能重放、能回退。

## 为什么不是直接改源码

安装包里的界面（`runtime/native-frontends/<build>/`）是编译好的 Next.js 产物，本机没有 r9.2 之后的前端源码
（GitHub 仓库 johana425a/mult 停在 r8）。所以界面改动用"复制一份构建 → 打补丁 → 切换"的方式做：

1. 复制当前构建：`runtime/native-frontends/<旧build>` → `runtime/native-frontends/<新build>`，旧的原样保留。
2. 在副本里改编译后的 chunk。改过的 chunk 必须换文件名（同长度的新哈希），并把 `.next-*` 目录里所有引用一起替换，
   否则 Electron 的 HTTP 缓存（`cache/desktop-browser`）会继续给出旧文件。
3. 新增的组件在服务端渲染时不出现、挂载后再显示，这样不用改服务端 chunk，也不会触发 hydration 报错。
4. 备份 `runtime/native-frontend.json`，再把它指向新构建。重启 DeepSteam 生效。
5. 回退：把备份的 json 复制回 `runtime/native-frontend.json`，重启。

后端 Python 代码有两份，需要同时改：`runtime/python/Lib/site-packages/deeptutor/` 和
`runtime/deeptutor-packages/deeptutor/`（参考 `reports/domestic-video-fix.json` 的做法）。

## 补丁列表

| 日期 | 目录 | 基于 | 内容 |
| --- | --- | --- | --- |
| 2026-10-15 | `20261015-sidebar-workspace/` | `20261014-video-session` | 侧边栏"工作区 +"按钮（展开栏标题行 + 收起栏图标，Ctrl+O）：选文件夹 → 登记为工作区 → 在其中新建对话 |
| 2026-10-15 | `20261015-ui-refresh/` | `20261015-sidebar-workspace` | 配色：琥珀标本底色 + H&E 染色图标色；内容区圆角面板、顶部微光、中文字体回退（不再掉到宋体）、侧边栏当前项、输入框聚焦光圈、细滚动条；新增模型厂商的图标 |
| 2026-10-15 | `20261015-providers/` | 后端 deeptutor 两份副本 | 新增 21 个模型提供方（xAI、Cohere、Perplexity、Upstage、混元、百川、Together、Fireworks、DeepInfra、Cerebras、SambaNova、Hugging Face、Nebius、Vercel AI Gateway、GitHub Models，以及 Kimi/Qwen/GLM/MiniMax/SiliconFlow 的海外或国内平台）；首次运行按系统语言选择界面和回复语言。原文件备份在 `backup/` |

重放 2026-10-15 补丁（需要 Node 18+）：

```
node patches/20261015-sidebar-workspace/apply-sidebar-workspace.cjs ^
  runtime/native-frontends/<复制出的新目录> patches/20261015-sidebar-workspace/sidebar-workspace-inject.js
```

脚本会先核对目标 chunk 的锚点各出现一次、语法能解析，再改名、改引用，最后在构建目录写
`DEEPSTEAM-LOCAL-PATCH.json`。

## 关于"让工作区智能体改自己"

目前做不到，而且是有意设计的：`runtime/harness/sidecar.mjs` 把整个 DeepSteam 安装目录列为受保护路径，
工作区智能体（Harness）在这里既不能读也不能写，这个目录也不能登记成工作区。要放开，需要先决定放开到什么程度
（只放开程序代码，数据、凭据、缓存继续保护；或者让智能体只改目录外的一份副本，再由你手动应用）。

## 回退

- 界面：双击 `D:\DeepSteam-Standalone\恢复上一版界面.cmd`，选 1 只撤销配色，选 2 回到 10 月 14 日的界面。
- 模型厂商：双击 `D:\DeepSteam-Standalone\撤销模型厂商扩展.cmd`，从 `20261015-providers/backup/` 复制回原文件。
- 两者都需要从托盘彻底退出 DeepSteam 再打开。
