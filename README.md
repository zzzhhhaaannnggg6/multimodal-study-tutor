# Multimodal Study Tutor

将课件、教材和教师语音/转写重建为可追溯、可复习的课堂。

这个项目的核心不是把 PPT 压缩成摘要，而是把视觉材料作为主线，把课堂语音作为语义增量，并让每条重要结论可以回到页码、时间戳或其他来源。它适用于计算机系统，也可通过 profile 扩展到数学、科学、历史、语言和专业课程。

## 当前版本

`0.2.0` 是面向大学生自学的本地优先版本，包含：

- 无第三方运行时依赖的 lesson-map 数据模型和验证器；
- `study` CLI：初始化项目、登记输入、生成 provenance scaffold、验证和导出；
- 无依赖的 VTT/SRT、DOCX 段落、PPTX 文本页和 Markdown 阅读片段提取；
- Provider-neutral Agent API，以及可选的 OpenAI 适配器；
- 学生讲义层：学习路线、知识单元精讲、完整例题、易错点、练习和答案；
- 原生 HTML/CSS/JS 的学习路线与闭卷复习界面；
- 脱敏最小样例和 GitHub Actions 检查。

`build` 仍然只生成“输入清点与来源骨架”。`generate` 会把已有的
`lesson-map` 转换成学生可以直接阅读的 `study-guide`。没有文本模型时，输出会明确标为“教学草稿”，不会把摘要冒充成完整课程。

## 5 分钟试用

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
# 如果输入包含原始音频，可额外请求带时间戳转写
study generate /tmp/my-lesson --speech-provider openai
```

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
src/mst/guide.py        # 面向学生的自学讲义生成、验证和导出
src/mst/agent.py        # Provider-neutral 查询/解释接口
src/mst/providers.py    # Mock 与可选 OpenAI provider
src/mst/cli.py          # study 命令行入口
web/                    # 本地学生学习路线与闭卷复习
schemas/                # lesson-map 和 study-guide JSON Schema
examples/               # 可公开的最小 fixture
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
```

如果环境没有 pytest，至少可以运行：

```bash
python -m compileall -q src
python -m mst.cli validate examples/minimal_course/lesson-map.json --strict
```

Profile 编写规则见 [docs/profile-authoring.md](docs/profile-authoring.md)，隐私和数据边界见 [docs/privacy-and-data.md](docs/privacy-and-data.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。
