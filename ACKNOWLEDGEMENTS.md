# 署名致谢 / Acknowledgements

`directors-book` 的写法和规则借鉴了下面这些来源的**思路**。我们**没有拷贝它们的原文**，规则是用自己的话重新写的。「许可证」一栏是整理时（2026 年 10 月）在 GitHub 上看到的，之后可能变化；没有许可证的仓库默认保留所有权利，我们只借鉴了思路。

> 这份清单基于对各来源的阅读整理，**有些来源我只读了一部分**，借鉴点可能不完整或不准确。如果你是原作者，发现遗漏、错误或不希望被列入，请开 issue 告诉我们。

## 视频提示词与 Seedance 相关

| 来源 | 许可证 | 借鉴的思路 |
|---|---|---|
| [dexhunter/seedance2-skill](https://github.com/dexhunter/seedance2-skill) | MIT | `@` 引用要写明用途、镜头词表 |
| [MapleShaw/seedance2.0-prompt-skill](https://github.com/MapleShaw/seedance2.0-prompt-skill) | MIT | 角色参考图与首帧图的写法、运镜坐标编码的思路、剪辑节奏 |
| [jnMetaCode/ai-shortfilm-prompts](https://github.com/jnMetaCode/ai-shortfilm-prompts) | MIT | 用具体名词代替形容词、瑕疵与克制、交付前自检 |
| [liyue-aigc/seedance-2-5-video-director](https://github.com/liyue-aigc/seedance-2-5-video-director) | MIT | 素材锁定、情绪反应要有触发顺序、台词时长审查 |
| [alchaincyf/seedance-skill](https://github.com/alchaincyf/seedance-skill)（花叔） | MIT | 参考图要素、技术术语优先于形容词、标明实测边界 |
| [Arch-Dog/video-prompt-engineer](https://github.com/Arch-Dog/video-prompt-engineer) | MIT | 音频台账、动作因果与走位检查、固定资产只给反复出现的元素命名 |
| [OSideMedia/higgsfield-ai-prompt-skill](https://github.com/OSideMedia/higgsfield-ai-prompt-skill) | MIT | 公式化提示词的组织思路（只读了标题） |
| qianye-wuyu/dual-model-video-prompt | 无许可证 | 用具体的肌肉变化替代情绪形容词（仅思路） |
| liangdabiao 的两个 Seedance skill、songguoxs/seedance-prompt-skill | 无许可证 | 按场景分流、时间戳分镜的思路（仅思路） |
| mx-shell、seedance-20（上游仓库未确认） | seedance-20 声明 MIT | 物理直述、禁止文学化修辞、台词嵌入动作；非主动结果不写成终点、一个镜头一个主动作 |

## 剧本、分镜与摄影

| 来源 | 许可证 | 借鉴的思路 |
|---|---|---|
| [lixiaoxiao9888-create/manju-laoli-skill](https://github.com/lixiaoxiao9888-create/manju-laoli-skill)（漫剧老李） | MIT | 「废切」判据、台词语感与称呼系统、外来剧本只补不改、段缝与尾帧锚定、画幅作为前置问题、过渡是戏点；场景资产的三类图分工、一张图多视角只占一个参考图名额、按空间类型选机位、空间事实先定、状态变体共享布局、年代锚 |
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | MIT | 单集（故事）契约、「所以／但是」检验、转折写成可见动作、公平揭示 |
| [eternityspring/shuohao-skills](https://github.com/eternityspring/shuohao-skills) | Apache-2.0 | 动作与台词交替（原文叫「节拍流」，我们的体例已改用中文场号制）、每场至少一个动作节拍、动作只写常见动作、时长预算 |
| [jtydhr88/screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | MIT | 人物与冲突、对白是行动、对白三层、剧本格式与动作段落写法（这些 skill 本身提炼自多本编剧书籍） |
| [geegl/directorskills](https://github.com/geegl/directorskills) | MIT | 180 度法则、主场景法、灯光方向与情绪（提炼自 Blain Brown 等的摄影书籍） |
| [62656456/ai-film-skills](https://github.com/62656456/ai-film-skills) | Apache-2.0 | 观看先于术语、手持要写明晃动来源、运动要解释框内关系 |
| MasterLeos/leos-six-department-directing-team-skill-v1 | 无许可证 | 相邻镜头的出口与入口状态、关键道具的初始变化结果、背景人物各有动作（仅思路） |
| fanchengchen1-collab/super-director | 未声明 | 先情绪后技术、动机光、先画调度图、默认无配乐（仅思路） |

## 其他

| 来源 | 借鉴的思路 |
|---|---|
| foyege（抖音「Foyege 的 AIGC 进阶之路」讲解） | 三层提示词结构、表演控制、对白话轮与言语不流畅、悲伤的三股力量、AU 作为描述的补充、多人站位与白模思路、皮肤六段式 |
| 《一镜到底第一期》文档（作者：Surviving-黑猫阿） | 摄影机像有惯性的低空无人机、背景人物各有节奏的写法 |
| 用户提供的人物提示词截图（来源待补，据称来自「花椒叔」） | 人物提示词的五块结构（身份、皮肤、光影、镜头质感、反向限制） |
| 用户提供的「电影感自然出图」skill（无许可证，结尾带推广） | 场景提示词的组装顺序（仅借鉴结构） |
| 「AI 对风的表达」视频（White Lab） | 楼下外景的影调描述（仅描述影调，不借内容） |
| [Agent Skills 开放标准](https://agentskills.io/specification)、Claude Code 与 Codex 官方文档 | skill 的目录与 frontmatter 格式 |

## 说明
- 上面的「借鉴」指思路层面。摄影和编剧两类来源本身是从书籍提炼的，**我们没有拷贝书籍或这些仓库的文字**，使用时请去读原书。
- 如果你发现这里有不准确的写法、错误的许可证信息或遗漏的来源，欢迎提 issue。

## 图标

README 横幅和 `assets/logo.svg` 里的场记板图标是 [Lucide](https://lucide.dev/icons/clapperboard) 的 `clapperboard`，ISC 许可。按许可要求保留下面的声明：

```
ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

图标本身用的是白色线条，放在我们自己画的圆角方块里；方块和横幅的排版是本项目自己的设计，随本项目的 MIT 许可。

