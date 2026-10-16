# DeepSteam 便携版（2026.10.13-r9-selected-model-vision）

这是已经修好的**完整可运行副本**：解压即可用，不需要联网安装，也不需要另外装 Python / Node / 模型。

## 一、系统要求

| 项目 | 要求 |
|---|---|
| 系统 | 64 位 Windows 10 / 11 |
| 磁盘 | 解压后约 6 GB（含 MinerU 版面解析模型约 2 GB） |
| 内存 | 建议 8 GB 以上（本地 OCR/解析时占用较高） |
| 网络 | 首次安装不需要；使用 AI 功能需要能访问 DeepSeek 官方服务 |
| 账号 | 需要你自己的 DeepSeek 账号或 API Key（不随包提供，也不包含原机主的任何账号） |
| 路径 | **任意路径均可**（建议纯英文、无空格，例如 `D:\DeepSteam`） |
| 运行库 | 依赖系统自带的 VC++ 2015-2022 运行库（Win10/11 默认具备；原安装程序同样未内置） |

## 二、安装步骤

1. 把压缩包解压到目标位置，使目录结构为 `<你选的目录>\DeepSteam\DeepSteam.exe`。
   - 请用能完整解压大量小文件的工具（7-Zip / WinRAR / Windows 自带解压均可）；
     若解压中断或不完整，重跑下面的步骤会报错，重新解压即可。
   - 包内**不含** junction（目录联接）实体：首次运行会自动重建全部 899 个（与原安装程序一致）。
2. 双击 `Setup-DeepSteam-Portable.ps1`（右键 → 使用 PowerShell 运行），或在 PowerShell 中执行：
   ```
   powershell -ExecutionPolicy Bypass -File .\Setup-DeepSteam-Portable.ps1
   ```
   它会：检查系统 → 重建依赖联接 → 写入安装标记 → 创建桌面快捷方式。
3. 双击桌面 `DeepSteam`（或运行 `Start-DeepSteam.cmd`）启动。
4. 首次进入「连接模型」页：点「登录 DeepSeek」完成官方授权，或粘贴你自己的 API Key。
   连接成功后，"学习 / 课堂 / 对话" 才能调用模型。

## 三、包内包含 / 不包含

包含：程序、桌面端、本机 Python 与 Node 运行时、文档解析（含离线 OCR 与 MinerU 权重）、
渲染服务、DeepTutor 前端与互动课堂前端、原有修复补丁、`_repair-kit/`（修复脚本与说明）。

不包含（**已刻意剔除**）：原机主的用户数据（教材、课程、课堂、对话记录）、
浏览器会话与 Cookie、DeepSeek 账号凭据（DPAPI 加密文件）、运行日志、缓存、进程日志。

## 四、常见问题

- **端口被占用**：程序使用 `127.0.0.1` 的 3791-3796、8011。若报"服务未启动"，先关掉占用这些端口的程序，
  或运行 `Stop-DeepSteam.cmd` 后再启动。
- **杀毒软件拦截**：本地 Python/Node 与 OCR 模型可能被误报，请将整个目录加入白名单。
- **没有声音**：课堂的"教师旁白"需要课堂生成到配音阶段才会产生音频；仅当课堂生成被质量核验驳回时才会没有旁白。
- **语音输入（麦克风）报网络错误**：该功能使用浏览器内置识别与在线语音识别服务，需要配置 ASR 服务
  （本机语音合成是离线的，但本机识别不是）。
- **关闭程序**：托盘图标右键 →「退出并暂停」；`Stop-DeepSteam.cmd` 亦可。
- **卸载**：直接删除整个目录即可（不会写注册表、不会留下系统服务）。
  如需清理快捷方式，删除桌面上的 `DeepSteam` 与 `Stop DeepSteam` 两个快捷方式。

## 五、完整性校验（可选）

`PORTABLE-MANIFEST.sha256` 记录了包内每个文件的 SHA256。传输后可在该目录执行：

```
powershell -Command "Get-Content .\PORTABLE-MANIFEST.sha256 | ForEach-Object { $h,$p = $_ -split '  ',2; if ((Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash -ne $h) { Write-Host \"MISMATCH $p\" } }"
```

没有输出即表示所有文件与打包时一致。
