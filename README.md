# directors-book（导演手册）

[English](README.en.md)

> **版本 5.0.0。** 这个版本号接着之前做过的 directors-book（旧版 2.0.1，已不再维护）：名称和结构相近，但内容是重新写的，不兼容旧版。skill 的文件都已写完，已在 Claude Code、Codex、WorkBuddy 里测过（短剧、影视；有几次测试被污染过，见 `tests/`）；提示词写法的多数规则没有做过对照实验，见下面的「已知限制」。

`directors-book`（导演手册）是一个面向 Seedance 视频生成的 agent skill。它帮你把一个想法一步步变成可以直接复制使用的剧本、分镜、人物与场景资产提示词、视频提示词，并整理成一个可一键复制的 HTML「导演手册」。

## 它能做什么

四个阶段，每一个都可以单独使用：

1. **剧本**：短剧或影视两类（开始前先问体裁）。
2. **分镜**：镜头速览表（接近行业分镜表）、镜头正文、片段划分、合镜检查。
3. **资产包**：人物提示词（人物四视图：三视图加面部近景）和场景提示词（母版、场景多机位、走位图）。
4. **视频提示词**：整体概念、参考素材绑定、分镜、声音、反向限制。

另外还有一个选项：**导演手册**，即完整的四个阶段，交付为一个排版固定的 HTML 文件（剧本、分镜、资产提示词、视频提示词；视频提示词按第一段、第二段放在最后，都可一键复制）。

开始前会先问**体裁**（带了剧本也问）、**画幅**和**模型版本**（Seedance 2.0 或 2.5），按任务取舍；有弹窗提问工具的 agent 会用弹窗。剧本和分镜都确认之后，还会问接下来要导演手册还是只要提示词。

## 安装

这个 skill 遵循 [Agent Skills 开放标准](https://agentskills.io/specification)，Claude Code 和 Codex 都可以使用。

**方式一：命令安装**

```bash
npx skills add Jay-make8/directors-book
```

这条命令由第三方工具 [skills](https://github.com/vercel-labs/skills) 提供，会去本仓库里找到 `directors-book`，再装到你选的 agent 里；加 `-g` 装到用户级目录，用 `-a` 指定 agent。我们验证过它能在本仓库里发现这个 skill，各 agent 里的实际安装没有逐个验证。

**方式二：手动复制**

下载 [Release](https://github.com/Jay-make8/directors-book/releases) 里的压缩包（或克隆本仓库），把 `directors-book` 这个目录复制到对应位置：

| agent | 用户级（所有项目） | 项目级 |
|---|---|---|
| Claude Code | `~/.claude/skills/directors-book/` | `<项目>/.claude/skills/directors-book/` |
| Codex | `~/.agents/skills/directors-book/` | `<项目>/.agents/skills/directors-book/` |

安装路径来自两家官方文档，可能会变，以官方文档为准：
- Claude Code：<https://code.claude.com/docs/en/skills>
- Codex：<https://learn.chatgpt.com/docs/build-skills>

安装后重启会话。

## 使用

直接说你的需求即可，例如：

- 「帮我写一个短剧剧本」
- 「把这份剧本拆成分镜」
- 「给这个人物出一份资产提示词」
- 「生成导演手册」

## 仓库结构

```
directors-book-repo/
├── skills/directors-book/     skill 本体
│   ├── SKILL.md               入口：四个阶段、硬规则、路由
│   ├── references/            按需读取的规则（剧本、分镜、资产、视频提示词、自检等）
│   ├── examples/              示例，含一份 handbook.json 填写示例
│   ├── assets/                导演手册的 HTML 模板
│   └── scripts/               build_handbook.py：生成 HTML
├── tests/                     手动测试方案和实测记录
├── README.md / README.en.md
├── ACKNOWLEDGEMENTS.md        署名致谢
├── CHANGELOG.md
└── LICENSE
```

## 已知限制

- 生成导演手册 HTML 需要能运行 `python3`（3.8 及以上，只用标准库）；环境里不能运行时，退回同结构的 Markdown，并告诉你没有生成 HTML。
- 本项目的写法和规则多数来自对其他 skill、教程和实际出图反馈的整理，**大部分没有做过系统的对照实验**，效果因模型和平台而异。
- Seedance 2.0 与 2.5 的时长、图片数量等数字来自第三方文档，没有字节跳动的官方页面，仅作默认值，你可以按自己的平台覆盖。
- 提示词的字数上限没有统一的官方数字，不同来源说法不一致。

## 许可证

[MIT](LICENSE)

## 致谢

这个项目借鉴了很多人的思路，详见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。
