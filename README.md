# Multimodal Study Tutor

将课件、教材和教师语音/转写重建为可追溯、可复习的课堂。

这个项目的核心不是把 PPT 压缩成摘要，而是把视觉材料作为主线，把课堂语音作为语义增量，并让每条重要结论可以回到页码、时间戳或其他来源。它适用于计算机系统，也可通过 profile 扩展到数学、科学、历史、语言和专业课程。

## 当前版本

`0.2.0` 是面向大学生自学的本地优先版本，包含：

- 无第三方运行时依赖的 lesson-map 数据模型和验证器；
- `study` CLI：初始化项目、登记输入、生成 provenance scaffold、验证和导出；
- 无依赖的 VTT/SRT、DOCX 时间片段、PPTX 文本页和 Markdown 阅读片段提取，以及可选的 PDF 提取；
- Provider-neutral Agent API，以及可选的 OpenAI 适配器；
- 学生讲义层：学习路线、知识单元精讲、完整例题、易错点、练习和答案；
- 原生 HTML/CSS/JS 的学习路线与闭卷复习界面；
- 脱敏最小样例和 GitHub Actions 检查。

当前讲义生成器会把每个知识单元组织成“先想 → 看材料 → 教师补充 → 导师补链 → 完整例题 → 易错对照 → 回忆/过程/迁移练习”。准备阶段还会记录 PPTX 形状、代码/公式/流程线索，以及教师片段的定义、推导、例题、纠错和评价角色。
计算机系统 profile 还会从课件中识别常见的 RISC-V 执行、进制转换和二进制运算例题；没有足够材料时会保留“待补充”状态，不会伪造数值或教师观点。

最近的改动集中在防止错误讲解：DOCX 中单独一行的时间标记会与后续讲话合并，
课次配对证据不足的语音不会进入正文，PPT 上下标与连接线的方向会分别保留。
已识别的指令会说明实际读取和写入的操作数；`muli` 等课件教学记法会注明与标准指令集的区别。
模型缺少例题步骤或练习时，程序保留缺口，不再用通用句凑齐“完整讲义”。

本地网页现在支持独立生成任务、阶段提示和失败重试。刷新页面会重新读取任务；
关闭本地服务后，未完成的任务可以用已保存的材料重新生成。每次导入单独保存，
文件损坏或生成失败不会替换已有讲义。阅读位置、完成标记和练习草稿分别保存；
单元内容修订后，对应的旧完成标记和旧答案不会继续算作有效进度。
网页还会逐文件说明读到了多少页或转写片段、哪些录音尚未转写，以及下一步应补什么。
选择“补充或修复这次材料”，可保留课件、只补交转写，或取消勾选坏文件后添加新版；
不必重新上传整套材料。补充流程沿用本课学习记录，另开课程时则单独保存。

没有知识地图时，明确选择文本模型会先提出整课规划，再按先修关系逐单元讲解；
跨页合并必须保留每个来源的原文锚点，遗漏来源或循环依赖会退回草稿。
学生可从知识点直接返回先修讲解。离线模式只合并明确的同标题页，未形成主线时如实提示。
重复解题步骤、同题换标签和解析照抄答案等内容也不能通过严格检查；
这些规则仍不能代替教学正确性评测与学生独立学习验收。

数制转换现按材料中的实际数字使用精确分数计算，展示逐步过程、可作答的变式，
并保留材料答案与计算结果的冲突。普通二进制加减法还会逐列展示进位/借位，配套具体的过程题与迁移题。
`study evaluate` 现有三份共 110 个公开合成案例，
检查实际答案、练习和来源；范围与运行方式见 [教学正确性评测](docs/evaluation.md)。
这项评测不能代表整门课程的正确率，也没有替代专家审阅或学生盲测。

这些改动不代表所有课程已经可以完全独立学习。当前内容深度、知识分组和人工验收的边界见
[质量状态](docs/quality-status.md)。

`build` 仍然只生成“输入清点与来源骨架”。`generate` 会把已有的
`lesson-map` 转换成学生可以直接阅读的 `study-guide`。没有文本模型时，输出会明确标为“教学草稿”，不会把摘要冒充成完整课程。

## 桌面预览

已提供原生 macOS 预览构建：解压后双击「听课助手.app」，直接选择材料并进入学习页面，
学生运行时不需要安装 Python 或输入命令。课程与学习记录保存在应用之外，重开可继续学习。
应用内置 PDF 原页预览，讲解旁可翻看课件、放大核对；导出的 HTML 自带已生成原页，可离线对照。
当前本机构建仅验收 Apple 芯片、macOS 26.0+；尚未完成正式签名、公证与其他平台适配。
使用方法、构建方式和剩余限制见 [桌面预览](docs/desktop-preview.md)。

## 开发者 5 分钟试用

要求 Python 3.10+。在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

study init /tmp/my-lesson --subject generic
study ingest /tmp/my-lesson examples/minimal_course
study build /tmp/my-lesson
study generate /tmp/my-lesson
study validate --project /tmp/my-lesson --strict
study export /tmp/my-lesson --format md
study serve /tmp/my-lesson
```

然后打开 `http://127.0.0.1:8765/`。也可以直接用仓库内的演示数据：

```bash
python -m http.server 8765 --directory web
```

macOS 用户装有 Python 3.10+ 后，可双击仓库根目录的 `start-study.command`。
网页会直接打开，在页面选择或拖入材料并选择学科；默认工作区在
`local-data/my-study/`，下次打开会恢复已有讲义，不重复生成。
这个脚本入口仍需要 Python；不需要 Python 的独立应用使用上面的桌面预览构建。

网页默认只使用本地处理；已有录音转写可复用，未转写录音不会自动上传。
添加录音后，可在“录音怎么处理？”中选择转写服务，核对录音列表与地址并单独确认；
转写与模型讲解使用各自的密钥和发送范围，密钥不保存。后续录音失败后，重试只发送未完成的录音。
也可在网页选择“模型讲解”，填写 OpenAI 或兼容服务的模型与密钥，核对发送范围后确认。
密钥只用于这次生成，不写入课程文件；刷新后不会恢复或自动再次调用。
没有通过教学完整性检查的模型回答不会替换旧讲义。该入口不需要额外安装模型 SDK。
单次最多 60 个文件、合计 100 MB。旧版 `.ppt` 需要先另存为 `.pptx`。

`quickstart` 和 `build` 默认会尝试把 PPT/PDF 渲染到项目的
`derived/rendered/`，供来源附录和视觉复核使用；使用 `--no-render` 可关闭。
开发者安装 `python -m pip install -e '.[pdf]'` 可获得本地 PDF 文字读取与页面渲染，
不需要另装 Poppler。PPT 完整页面预览仍需要 LibreOffice，或先将课件另存为 PDF。
仅有图片的扫描页可预览，但没有自动 OCR，不能据此生成完整讲解。
如果明确选择 `--vision-provider openai`，程序只上传已渲染的页面图像进行结构观察，
结果仍标为待人工复核，不会自动变成教师观点或已核验公式。

`examples/minimal_course` 中的 `.md` 和 `.vtt` 是合成材料，运行 `ingest`、
`build` 和 `generate` 后会生成页面、时间段和学生讲义；它们不代表真实课程或教师。

生成其他格式：

```bash
study export /tmp/my-lesson --format html
study export /tmp/my-lesson --format json
study validate-guide /tmp/my-lesson/derived/study-guide.json --strict
```

如果已安装可选模型依赖，可以让 provider 补全解释、例题和练习：

```bash
python -m pip install -e '.[openai]'
study generate /tmp/my-lesson --provider openai --model gpt-5-mini
# 如果输入包含原始音频，可显式请求分段转写（默认 whisper-1）
study generate /tmp/my-lesson --speech-provider openai
```

转写密钥从 `OPENAI_API_KEY` 读取。默认模型请求分段时间戳；主动指定
`--speech-model gpt-4o-transcribe` 等模型时使用 JSON，未返回时间的文字保留为待定位，
不推算时间。每段录音的本工具上传上限为 24 MB，整批在发送前检查；超限可压缩、分段
或改交 SRT/VTT。自动转写不自动重试，已完成录音会复用本地结果。
网页也支持显式选择录音转写；默认不上传，补材料时只继承勾选保留录音的转写。

## 证据契约

理解优先级与评价证据是两条独立轴：

- `U3/U2/U1/U0`：理解骨架、重要应用、桥接/前置、背景；
- `E3/E2/E1/E0/E-`：明确评价要求、强信号、课堂强调、未观察到信号、明确排除。

`E0` 不等于“不考”。`E3` 和 `E-` 必须带可定位的证据；无法定位时验证器会拒绝该主张。教师内容、材料内容、导师补链、综合判断和待确认状态必须显式区分。

## 代码结构

```text
src/mst/models.py       # 可移植 lesson-map dataclass
src/mst/validation.py   # 来源、等级、对齐和隐私检查
src/mst/ingest.py       # 输入清点与哈希 manifest
src/mst/extract.py      # PPTX/Markdown/VTT/SRT/DOCX 的保守文本提取
src/mst/reconstruct.py  # 离线 provenance scaffold
src/mst/planning.py     # 整课规划、原文锚点、来源覆盖和先修图检查
src/mst/guide.py        # 面向学生的自学讲义生成、验证和导出
src/mst/teaching.py     # 空洞例题、重复练习和解释的可观察问题检查
src/mst/numerals.py     # 有明确条件的位置记数法精确例题
src/mst/answer_checks.py # 用位权和几何级数核对数值
src/mst/evaluation.py   # 合成教学案例的实际答案与来源评测
src/mst/agent.py        # Provider-neutral 查询/解释接口
src/mst/providers.py    # Mock 与可选 OpenAI provider
src/mst/cli.py          # study 命令行入口
web/                    # 本地学生学习路线与闭卷复习
schemas/                # lesson-map、course-plan 和 study-guide JSON Schema
examples/               # 可公开的最小 fixture
evals/                  # 公开合成题库，不含私人课程
```

## 设计边界

- 原始课程材料只读，默认不复制进公开仓库；
- 路径、教师语音和截图属于本地数据，不应提交到 Git；
- 模型补充不能伪装成教师原话；
- 没有足够证据时使用待确认，而不是猜测考试结论；
- 核心引擎不绑定单一模型厂商，离线 Mock 模式可用于测试和演示。

## 开发

安装开发依赖后运行：

```bash
python -m pip install -e '.[dev]'
python -m pytest
npm ci
npm test
npx playwright install chromium
npm run test:web
```

如果环境没有 pytest，至少可以运行：

```bash
python -m compileall -q src
python -m mst.cli validate examples/minimal_course/lesson-map.json --strict
```

Profile 编写规则见 [docs/profile-authoring.md](docs/profile-authoring.md)，隐私和数据边界见 [docs/privacy-and-data.md](docs/privacy-and-data.md)。
网页任务、进度保存和安装包检查见 [本地网页工作流](docs/local-web.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。
