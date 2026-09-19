---
name: aicomp-results
description: 通过 HTTP 请求向 reg.aicomp.cn 提交 AIC 赛题结果 ZIP 和作品名称、查询指定提交的通用分数及 mIoU（支持图像分割与噪声标签细粒度识别赛题），或读取全部公开排行榜分数。提交与个人查分需要用户提供 auth，公开排行榜无需登录。
---

# AIC 结果提交与查分

处理用户账号的结果提交、评分查询和公开排行榜读取，使用本技能的 `scripts/aicomp.py`，不模拟鼠标点击。

## 登录与目标

登录状态必须由用户提供：从登录后页面发出的 API 请求中取得 `auth` 请求头值。
它是认证请求头，不是这里需要保存的 Cookie。不自动登录，不查找浏览器密码、
Cookie 数据库或其他用户凭证，也不把过去账号的 token 内置为默认值。
当前会话中用户已经提供且仍有效的 token 可以复用；401/403 时停止并请用户提供新值。

通过单个进程的 `AICOMP_AUTH` 环境变量或 `--auth-stdin` 输入 token；
本地交互式终端也支持隐藏输入。不要把 token 放入命令行参数、文件、日志、
最终答复、Git 提交或持久配置。读取失败时不要自行切换用户账号。

所有记录查询都按认证账号筛选。账号只有一条报名记录时自动选中；
多条记录时，脚本返回候选队伍、赛题和记录 ID。明确目标后使用 `--record-id`，
不要猜测或选择其他账号的记录。

## 1. 提交结果

需要本地 ZIP 路径和作品名称。名称不超过 20 字，不能静默截断用户的名称。
用户要求提交即构成此操作的授权；只有缺少必要信息或目标不明时才询问。
只要求查分时不要提交。

```text
<python> <skill>/scripts/aicomp.py submit --title "<作品名称>" --file "<结果.zip>" [--record-id "<报名记录ID>"]
```

脚本校验 ZIP、提交期限、缴费状态，上传后回读验证；文件字段是 `ZPDAWD_`，
作品名称字段是 `CSZPMC_`。相同内容、相同名称且已提交时跳过重复写入。
真实提交会生成唯一文件路径，以区分每次评分。

保留标准输出中的 `receipt` 路径。它标识此次提交，查分时优先使用这个回执。
提交或回读超时意味着结果未确认，不能自动重试提交；先使用生成的回执查分、
检查页面状态，仍不明确时向用户说明。

## 2. 查询此次打分

```text
<python> <skill>/scripts/aicomp.py score --receipt "<提交回执.json>" --wait
```

没有回执时，查询当前账号指定报名记录目前挂载的 ZIP：

```text
<python> <skill>/scripts/aicomp.py score [--record-id "<报名记录ID>"] [--wait]
```

`--wait` 每 15 秒查询一次，最多 600 秒；可设置 `--interval` 和 `--timeout`。
这是当前命令内的有限等待，不创建后台定时任务。三分钟只是用户经验，
不要保证固定完成时间。失败或超时要如实报告，不重新上传。

评分来自 `ZPDFB` 表；`DQZT_=DONE` 为完成，`BZ_` 为页面评分文字，
例如 `打分成功，mIoU=0.692610`。只匹配本账号、参赛编号和回执文件，
并保留原始备注。分数也可能直接位于 `FS_`，而备注为空：
`score` / `score_text` 返回 `FS_` 数值及保留精度的文本，`score_source=FS_`。
噪声标签细粒度图像识别赛题就是这种形式，备注为空不代表没有分数。
`miou_text` 保留备注中的 mIoU 小数位；`miou=null` 时仍应检查 `score_text`。
不要把通用分数自动除以 100，或擅自解释为 mIoU/准确率。
只有 `DONE` 且无失败信息时才输出数值；其他状态可能仍携带旧分数。
提交成功不等于评分完成。报告作品名称/文件、状态、分数或失败原因；
不要向用户输出完整业务记录或 token。

分割赛题和噪声标签细粒度识别赛题使用相同的提交/查询协议。
按当前用户的报名记录确定赛题，不内置任何用户的账号、记录 ID 或登录凭证。
`/app/JSGLPT/65b75207a58fdc32c79e9842` 是共享的打榜状态页，
它本身不能确定用户所参加的赛题。文件名 `pred_results.zip` 也不能用于选定账号或赛题。

## 3. 查看排行榜全部分数

排行榜详情页可直接读取，不需要登录 token。页面 URL 形如：

```text
https://reg.aicomp.cn/special/phb/detail?id=<榜单ID>&rwId=<任务ID>&stbh=<赛题编号>
```

```text
<python> <skill>/scripts/aicomp.py leaderboard --url "<排行榜详情页URL>" --stage "初赛" --format csv --output "leaderboard.csv"
```

脚本先调用公开的 `POST /third/jsphb`（`type=JSJD`）取得阶段名称，
再调用同一接口（`type=JSDF`）读取全部排行榜记录。结果包含排名、参赛编号、
队伍名称、分数、提交时间和打分时间；默认输出 JSON，`--format csv` 可导出 CSV。
阶段未指定时使用页面发布的第一个阶段。该接口返回公开榜单，不会读取用户私有 token，
也不会触发提交、评分或任何写入操作。

## 运行环境与验证边界

安装器为技能创建 `.venv`；Windows 使用 `<skill>/.venv/Scripts/python.exe`，
其他系统使用 `<skill>/.venv/bin/python`。若没有虚拟环境，使用已安装
`requirements.txt` 依赖的 Python 3.10+。

退出码：0 完成；1 参数/认证/请求错误；2 评分失败；3 仍在等待或超时。
回执默认保存在 Windows `%LOCALAPPDATA%/aicomp-results`，
其他系统 `~/.local/state/aicomp-results`，可用 `AICOMP_STATE_DIR` 覆盖。
回执包含账号和业务标识，留在本地，不提交 Git。

认证、读取、文件比对与查分已完成真实请求验证。新 ZIP 上传和业务保存流程
依据前端协议实现，并有模拟测试；尚未完成真实写入的端到端验证。
不得把跳过重复提交或模拟测试描述成新文件提交实测成功。
