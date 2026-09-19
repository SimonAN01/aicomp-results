# AIC 结果提交与查分

**目前仅适配以下两个赛题：**

1. **无人机低空航拍图像语义分割**
2. **面向噪声标签数据的细粒度图像识别鲁棒微调**

下述提交、个人查分与排行榜功能的适配范围均限于这两个赛题。
其他赛题尚未适配或验证，即使使用相同网站或接口，也不代表兼容；
使用前需要单独核对提交字段、文件要求、评分格式和排行榜接口。

可安装的 Codex Skill，同时提供三个子命令的 Python 工具：

1. `submit`：提交作品名称（不超过 20 字）及结果 ZIP。
2. `score`：查询此次提交的评分，可等待评测完成。
3. `leaderboard`：读取排行榜详情页中的全部公开分数，可导出 JSON/CSV。

通过 HTTP 请求工作，无需点击网页。面向 `reg.aicomp.cn` 的学生账号，
是基于页面协议实现的非官方工具。登录状态始终由使用者提供，不包含账号密码或 token。

## 安装为 Skill

Python 3.10+：

```powershell
git clone https://github.com/SimonAN01/aicomp-results.git
cd aicomp-results
python install.py
```

安装到 `$CODEX_HOME/skills/aicomp-results`，未设置 `CODEX_HOME` 时使用
`~/.codex/skills/aicomp-results`；在技能内建立隔离 `.venv` 并安装依赖。
更新使用 `python install.py --update`。自定义路径用 `--skills-dir`；
自己管理依赖时可用 `--skip-deps`。

在能发现该技能的 Codex 会话中使用：

```text
用 $aicomp-results 提交 C:\results\result.zip，作品名称“分割模型v2”，然后查询此次评分。
```

## 提供登录状态

使用者自行登录网站，从浏览器 Network 中该站 API 请求的 `auth` 请求头复制其值。
这不是 `Cookie` 头。工具不接管浏览器登录、不保存或自动刷新 token，
也不会搜索浏览器凭证。token 失效时需要使用者重新提供。

直接在终端运行时，会隐藏提示输入 token。脚本调用可通过进程环境变量
`AICOMP_AUTH`，或 `--auth-stdin` 从标准输入读取一行传入。
不要把真实 token 写进代码、命令参数、`.env`、日志或 GitHub。

## 直接作为工具使用

在仓库中先安装依赖：

```powershell
python -m pip install -r skills/aicomp-results/requirements.txt
```

提交：

```powershell
python skills/aicomp-results/scripts/aicomp.py submit --title "分割模型v2" --file "C:\results\result.zip"
```

账号只有一条报名记录时会自动选择。多条记录时会停止并列出候选，
需追加 `--record-id "<报名记录ID>"` 指定目标。

提交返回 JSON，其中 `receipt` 是本地回执路径。用它查询**该次提交**：

```powershell
python skills/aicomp-results/scripts/aicomp.py score --receipt "C:\path\receipt_xxx.json" --wait
```

或者查询某条报名记录当前的结果文件：

```powershell
python skills/aicomp-results/scripts/aicomp.py score --record-id "<报名记录ID>"
```

`--wait` 默认每 15 秒查一次、最多 600 秒，可通过 `--interval`、`--timeout` 修改。
评分可能超过三分钟；等待超时不会重新提交。

查看排行榜详情页的全部分数（不需要登录 token）：

```powershell
python skills/aicomp-results/scripts/aicomp.py leaderboard `
  --url "https://reg.aicomp.cn/special/phb/detail?id=4832828643476639836&rwId=4829238709759119407&stbh=4829238709759119428" `
  --stage "初赛" --format csv --output "leaderboard.csv"
```

2026-09-19 实测该页面接口返回 `469` 条“初赛”记录，包含 `XH_`、`CSBH_`、`TDMC_`、
`FS_`、`ZPZHTJSJ_` 和 `DFSJ_` 等字段。`leaderboard` 是只读公开接口，
不需要提供 `auth`。

示例评分输出（节选）：

```json
{
  "outcome": "score_completed",
  "status": "DONE",
  "miou": 0.69261,
  "miou_text": "0.692610",
  "message": "打分成功，mIoU=0.692610"
}
```

## 两个已适配赛题的评分格式

已验证两种评分格式：

| 赛题 | 返回字段 |
| --- | --- |
| 无人机低空航拍图像语义分割 | `BZ_` 含 mIoU；`FS_` 为服务端分数 |
| 面向噪声标签数据的细粒度图像识别鲁棒微调 | `FS_` 为分数；`BZ_` 可以为空 |

`score` 命令新增 `score`、`score_text`、`score_source`。
其中 `score_text` 保留 `FS_` 原有精度；`miou`/`miou_text` 继续单独返回，
不把服务端通用分数自动转换成准确率或 mIoU。未完成或失败的记录不输出旧分数。
例如仅有数值分数时，输出可为（合成示例）：

```json
{
  "outcome": "score_completed",
  "status": "DONE",
  "score": 81.23456789012345,
  "score_text": "81.23456789012345",
  "score_source": "FS_",
  "miou": null,
  "message": ""
}
```

两种赛题使用相同的 `submit` 和 `score` 命令，由用户提供的登录状态及报名记录
确定目标；没有内置用户账号。作品名称由 `--title` 提供，例如：

```powershell
python skills/aicomp-results/scripts/aicomp.py submit --title "识别模型v2" --file "C:\results\pred_results.zip"
```

噪声标签细粒度识别赛题的公开排行榜：

```powershell
python skills/aicomp-results/scripts/aicomp.py leaderboard `
  --url "https://reg.aicomp.cn/special/phb/detail?id=4832828643476639839&rwId=4829238709759119407&stbh=4829238709759119431" `
  --stage "初赛" --format csv --output "recognition-leaderboard.csv"
```

`/app/JSGLPT/65b75207a58fdc32c79e9842` 是共享的个人打榜状态页，
不能代替公开排行榜详情 URL，也不能仅凭这个地址或 ZIP 文件名判断账号所属赛题。

标准输出为 JSON，进度和错误写标准错误。退出码：

| 代码 | 含义 |
| --- | --- |
| 0 | 提交确认 / 已存在同一提交 / 评分完成 |
| 1 | 参数、认证或请求错误 |
| 2 | 评分失败 |
| 3 | 评分未完成或等待超时 |

## 提交与查分的对应关系

- 作品名称写入 `CSZPMC_`，ZIP 写入 `ZPDAWD_`。
- 相同 ZIP、相同名称且状态已提交时跳过写入；其他提交使用新的唯一文件路径。
- 回执保存报名记录、文件路径、保存时间、SHA-256，并校验账号归属。
- 查分读取 `ZPDFB`，同时按提交人、参赛编号、完整文件 URL 过滤；
  `BZ_` 是页面显示的评分文字，`DQZT_=DONE` 表示完成。
- 使用回执时，即使报名记录后来挂了新文件，也继续查询回执中的文件。
  成功找到评分记录后还会返回固定该评分 ID 的新回执。
- 保存超时可能意味着服务端已接受请求。工具输出未确认回执并停止，
  不自动重试写入。先查回执或检查页面，再决定后续操作。

本地回执默认在 Windows `%LOCALAPPDATA%/aicomp-results` 或其他系统
`~/.local/state/aicomp-results`。可用 `AICOMP_STATE_DIR` 改路径。
回执和诊断快照可能包含账号业务信息，应该留在本地；没有登录 token。
仓库只包含实现、说明和合成测试数据。

## 验证范围

已真实请求验证：认证、报名记录查询、ZIP SHA-256 比对、评分查询。
噪声标签细粒度识别赛题也已验证本地 ZIP 与当前提交一致、跳过重复写入，
并按回执查询 `FS_` 分数。
已通过模拟测试验证：匹配文件和账号、旧分数排除、等待/失败/超时、
重复提交保护及提交载荷中的作品名称/结果字段。

噪声标签细粒度识别赛题已按用户要求完成真实写入验证：
ZIP 上传至新的 OSS 路径、下载比对 SHA-256、保存指定作品名称及文件路径、
回读确认状态为已提交，并按新文件路径匹配评分记录，等待 `DONE` 后读回 `FS_`。
上传、保存、按回执等待与查分的完整流程均已实测。
此次使用已有预测内容测试了新的上传与保存流程；不代表验证了任意新预测文件的格式。
分割赛题此前只验证了同文件跳过与查分，未单独实测真实写入。
前端协议或表单配置发生变化时需要重新检查适配，不能保证长期不变。

运行测试：

```powershell
python -m unittest discover -s tests -v
```
