# Multimodal Study Tutor

将课件、教材和教师语音/转写重建为可追溯、可复习的课堂。

这个项目的核心不是把 PPT 压缩成摘要，而是把视觉材料作为主线，把课堂语音作为语义增量，并让每条重要结论可以回到页码、时间戳或其他来源。它适用于计算机系统，也可通过 profile 扩展到数学、科学、历史、语言和专业课程。

## 当前版本

`0.1.0` 是本地优先的可运行基础版，包含：

- 无第三方运行时依赖的 lesson-map 数据模型和验证器；
- `study` CLI：初始化项目、登记输入、生成 provenance scaffold、验证和导出；
- 无依赖的 VTT/SRT、DOCX 段落、PPTX 文本页和 Markdown 阅读片段提取；
- Provider-neutral Agent API，以及可选的 OpenAI 适配器；
- 原生 HTML/CSS/JS 的同步课堂时间轴演示；
- 脱敏最小样例和 GitHub Actions 检查。

当前 `build` 会生成“输入清点与来源骨架”，不会假装已经完成 OCR、音频识别或教师语义判断。完整的视觉—语音对齐和课堂重建将在后续版本接入可替换的解析器与模型 provider。

## 5 分钟试用

要求 Python 3.10+。在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

study init /tmp/my-lesson --subject generic
study ingest /tmp/my-lesson examples/minimal_course
study build /tmp/my-lesson
study validate --project /tmp/my-lesson --strict
study export /tmp/my-lesson
study serve /tmp/my-lesson
```

然后打开 `http://127.0.0.1:8765/`。也可以直接用仓库内的演示数据：

```bash
python -m http.server 8765 --directory web
```

`examples/minimal_course` 中的 `.md` 和 `.vtt` 是合成材料，运行 `ingest`
和 `build` 后会自动生成页面与时间段；它们不代表真实课程或教师。

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
src/mst/agent.py        # Provider-neutral 查询/解释接口
src/mst/providers.py    # Mock 与可选 OpenAI provider
src/mst/cli.py          # study 命令行入口
web/                    # 本地同步课堂时间轴
schemas/                # JSON Schema
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
