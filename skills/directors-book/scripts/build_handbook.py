#!/usr/bin/env python3
"""把 handbook.json 生成为一个离线的导演手册 HTML（或同结构的 Markdown）。

用法：
    python3 build_handbook.py handbook.json                 # 生成 项目名_导演手册.html
    python3 build_handbook.py handbook.json -o out.html     # 指定输出路径
    python3 build_handbook.py handbook.json --md            # 生成同结构的 Markdown
    python3 build_handbook.py handbook.json --check         # 只校验，不生成
    python3 build_handbook.py 调度.json --layout            # 交付分镜时，只画调度图并核对（见 references/readback.md）

只用 Python 标准库，兼容 Python 3.8 及以上。字段说明见 references/handbook-html.md。
版式固定：剧本 → 分镜 → 资产提示词 → 视频提示词（第一段、第二段……放在最后），每次生成都一样。
"""

import argparse
import html
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "handbook-template.html"
SKILL_MD_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def skill_version():
    """从 SKILL.md 的 metadata.version 读版本号，写进手册顶栏，避免以后拿旧版手册当新版用。"""
    try:
        m = re.search(r'^\s*version:\s*"?([^"\n]+)"?', SKILL_MD_PATH.read_text(encoding="utf-8"), re.M)
        return m.group(1).strip() if m else "未知"
    except OSError:
        return "未知"

SHOT_TITLE_RE = re.compile(
    r"^镜头\s*(\d+)｜(内景|外景)｜(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*秒｜(.+)$"
)
NEGATIVE_LEAD = "以下内容一律不要出现"

DEFAULT_MAX_SECONDS = {"2.5": 30, "2.0": 15}
DEFAULT_MAX_IMAGES = {"2.5": 30, "2.0": 9}

# 人物图的名称：这两个叫法在【参考素材绑定】里都只写人物名，不加括号
CHARACTER_SHEET_LABELS = ("人物四视图", "四格图")
# 参考帧（上一段最后一帧）的 label 写这个时只当状态参考，不当首帧：接缝是切换景别或机位时用
STATE_FRAME_LABELS = ("状态参考",)

# 场景图在【参考素材绑定】里的叫法（「四视图」是旧名，当作「场景多机位」处理）
# 「俯视平面图」是 5.6 的旧名，当作「俯视图」处理
SCENE_ROLE = {"母版": "主图", "场景多机位": "多机位", "四视图": "多机位", "走位图": "人物走位",
              "俯视图": "俯视图", "俯视平面图": "俯视图", "反打": "反打",
              "45°全景": "斜俯视", "45度全景": "斜俯视", "斜俯视全景": "斜俯视"}
# 单张角度图的 label 以「角度图」开头，可以带说明，如「角度图·门口往里看」
ANGLE_LABEL = "角度图"


def scene_role(label):
    if isinstance(label, str) and label.startswith(ANGLE_LABEL):
        return "角度"
    return SCENE_ROLE.get(label, label)


# 方向图的朝向（摄影机朝哪个方位拍）：x 往东、y 往北，方位角北 0、东 90
COMPASS = {"北": 0, "东北": 45, "东": 90, "东南": 135, "南": 180, "西南": 225, "西": 270, "西北": 315}
DIRECTION_ROLES = ("主图", "反打", "角度")
FACING_TOLERANCE = 45.0   # 镜头朝向和方向图朝向相差在这个角度内，算有图
FOV_HALF = 40.0           # 视线左右这个角度以外算画外（平面粗算）
# 调度图的固定规格（references/readback.md「调度图的规格」）：每个镜头一格，宽 200 像素，北在上，
# 东西、南北同一个比例，四周各留 1 米，左下角画比例尺；改这些数要同步改文档
LAYOUT_WIDTH = 200.0
LAYOUT_TITLE_H = 18.0
LAYOUT_PAD_M = 1.0
LAYOUT_SCALEBAR_H = 16.0
LAYOUT_FOV_DRAW = 24.0    # 画出来的视野线（约 40mm 焦距感的水平半角）
# 段落没写 use 时默认上传这个资产的全部图；但场景同时有俯视图和走位图时，只传走位图：
# 走位图就是在俯视图上叠加的人物路线，两张都传等于同一张平面传两遍，还多占一个名额
def default_labels(labels):
    if "走位图" in labels:
        return [lab for lab in labels if scene_role(lab) != "俯视图"]
    return list(labels)

# 反向限制的项数上限：官方只确认字幕和音频两类；列多了容易把不想要的东西带进模型注意力，也容易和正文打架
NEGATIVE_MAX_ITEMS = 12

# 提示词长度的提醒线（不是下限）：不算参考素材绑定、【摄影与影调】和每镜的「光线：」段（影视必写，两个体裁按同一把尺子量分镜），
# 超过这个字数就警告：先删重复，还超就在镜头之间拆段；不能为了压字数删关键动作、台词、站位机位和光线段
PROMPT_CHARS_PER_15S = 2000
# 台词语速：超过这个字/秒，除了争吵、慌乱、抢话，基本说不完
SPEECH_MAX_RATE = 6.0
IMG_REF = re.compile(r"@图(\d+)")

# 视频提示词全篇用中文全角标点（音效的半角 <> 是官方写法，不算）
HALF_WIDTH = re.compile(r'[,;:?!()"]')

# 含糊的方向：「朝右后方」这类，模型不知道是谁的方向
VAGUE_DIRECTION = re.compile(r"[朝向往](?:左后方|右后方|左前方|右前方)")

# 拿摄影机给摄影机定位的说法：模型读不出位置，防跳轴要写谁在画面左右
ABSTRACT_CAMERA = re.compile(r"轴线|靠近(?:镜头|观众)的?一侧|(?:镜头|观众|摄影机)这一?侧|两人走来的")
# 影视体裁每个镜头另起的光线段；【摄影与影调】里不写画面左右（机位一换就变）
LIGHT_LEAD = "光线："
SCREEN_SIDE = re.compile(r"画面(?:的)?[左右]")
ABSTRACT_CAMERA_HINT = ("机位要写在哪个参照物旁（场景里的固定实物，或位置已写清的人）、朝哪个参照物看，防跳轴就写清谁在画面左、谁在画面右"
                        "（见 video-prompt.md「写法细节」）")

# 近景、特写里必须写清人物在画面哪一侧、看向哪一侧（物品特写写「画面里只有……」），否则切镜头后左右容易乱
CLOSE_SIZES = ("近景", "特写", "大特写")
CLOSE_POSITION = re.compile(r"画面(?:的)?[左右]|画面里只有|画面中只有|画面里没有人|画面中没有人")

# 台词：中文引号（也兼容半角引号）里的内容
QUOTE_RE = re.compile(r"[“\"](.*?)[”\"]")


def quote_chars(s):
    """只留汉字、字母、数字，用来比较台词和数字数。"""
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def restated_quote(body):
    """台词说完后又复述台词里的字（例如：说：“太像了。”说到“像”字时声音发颤），返回被复述的那段；没有就返回 None。

    官方提示：台词后面复述再追加语气、表情、动作描述，容易让模型生成字幕。
    """
    ms = list(QUOTE_RE.finditer(body))
    clean = [quote_chars(m.group(1)) for m in ms]
    for k in range(1, len(ms)):
        prev, cur = clean[k - 1], clean[k]
        if not cur or len(cur) >= len(prev) or cur not in prev:
            continue
        gap = body[ms[k - 1].end():ms[k].start()]
        after = body[ms[k].end():ms[k].end() + 2]
        if len(gap) <= 12 and (re.search(r"说到|念到|讲到|这句|这几个字", gap) or re.match(r"[字时]", after)):
            return ms[k].group(1)
    outside = QUOTE_RE.sub("", body)
    for k, c in enumerate(clean):
        if len(c) >= 3 and c in quote_chars(outside):
            return ms[k].group(1)
    return None

# 资产阶段的内部术语：视频模型看不懂，不能出现在视频提示词里
INTERNAL_TERMS = ("主机位", "母版", "俯视平面图", "俯视图", "场景多机位", "四视图", "走位图", "角度图")

# 视频提示词的块名由脚本统一添加；字段里如果又写了块名，自动去掉并给出警告
BLOCK_FIELDS = (("concept", "整体概念"), ("cinematography", "摄影与影调"), ("sound", "声音"),
                ("negative", "反向限制"))

CN_DIGITS = "零一二三四五六七八九"


def cn_num(n):
    if n < 10:
        return CN_DIGITS[n]
    if n < 20:
        return "十" + (CN_DIGITS[n - 10] if n > 10 else "")
    if n < 100:
        tens, ones = divmod(n, 10)
        return CN_DIGITS[tens] + "十" + (CN_DIGITS[ones] if ones else "")
    return str(n)


def seg_name(n):
    """第一段、第二段……"""
    return "第%s段" % cn_num(n)


def strip_block_name(text, name):
    s = text.strip()
    head = "【%s】" % name
    if s.startswith(head):
        s = s[len(head):].lstrip("\n").strip()
    return s


# ---------------------------------------------------------------- 校验


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, msg):
        self.errors.append("%s：%s" % (path, msg))

    def warn(self, path, msg):
        self.warnings.append("%s：%s" % (path, msg))


def is_text(v):
    return isinstance(v, str) and v.strip() != ""


def need_text(data, key, path, rep):
    if key not in data:
        rep.error("%s.%s" % (path, key) if path else key, "缺少这个字段")
        return None
    if not is_text(data[key]):
        rep.error("%s.%s" % (path, key) if path else key, "必须是非空文字")
        return None
    return data[key]


def normalize_script(raw):
    """剧本可以是一整段文字，也可以是 [{title, body}] 的列表；统一成列表。"""
    if isinstance(raw, str):
        return [{"title": "剧本", "body": raw}]
    return raw


def model_default(model, table, override):
    if override is not None:
        return override
    if isinstance(model, str):
        for key, val in table.items():
            if key in model:
                return val
    return None


def validate(data, max_seconds, max_images, rep):
    if not isinstance(data, dict):
        rep.error("根", "最外层必须是一个对象（{...}）")
        return

    need_text(data, "project", "", rep)
    genre = need_text(data, "genre", "", rep)
    if genre is not None and genre not in ("短剧", "影视"):
        rep.error("genre", "只能是「短剧」或「影视」，现在是「%s」" % genre)
    need_text(data, "ratio", "", rep)
    model = need_text(data, "model", "", rep)

    # 剧本
    if "script" not in data:
        rep.error("script", "缺少这个字段（一段文字，或 [{\"title\":…,\"body\":…}] 的列表）")
    else:
        script = normalize_script(data["script"])
        if isinstance(data["script"], str) and not is_text(data["script"]):
            rep.error("script", "不能为空")
        elif not isinstance(script, list) or not script:
            rep.error("script", "必须是非空文字，或非空的 [{title, body}] 列表")
        else:
            for i, sec in enumerate(script):
                p = "script[%d]" % i
                if not isinstance(sec, dict):
                    rep.error(p, "必须是 {\"title\":…, \"body\":…}")
                    continue
                need_text(sec, "title", p, rep)
                need_text(sec, "body", p, rep)

    # 资产
    asset_labels = {}  # 资产编号 -> 它的提示词名称列表
    if "assets" not in data:
        rep.error("assets", "缺少这个字段（没有资产时写 []）")
    elif not isinstance(data["assets"], list):
        rep.error("assets", "必须是列表")
    else:
        for i, a in enumerate(data["assets"]):
            p = "assets[%d]" % i
            if not isinstance(a, dict):
                rep.error(p, "必须是对象")
                continue
            aid = need_text(a, "id", p, rep)
            need_text(a, "name", p, rep)
            need_text(a, "kind", p, rep)
            if aid is not None and aid in asset_labels:
                rep.error(p + ".id", "编号「%s」重复" % aid)
            labels = []
            prompts = a.get("prompts")
            if not isinstance(prompts, list) or not prompts:
                rep.error(p + ".prompts", "缺少，或不是非空列表（每项 {label, text}）")
            else:
                for j, pr in enumerate(prompts):
                    pp = "%s.prompts[%d]" % (p, j)
                    if not isinstance(pr, dict):
                        rep.error(pp, "必须是 {\"label\":…, \"text\":…}")
                        continue
                    lab = need_text(pr, "label", pp, rep)
                    txt = need_text(pr, "text", pp, rep)
                    if lab is not None:
                        labels.append(lab)
                    if lab in CHARACTER_SHEET_LABELS and txt is not None and not ("横向排列" in txt and "从左到右" in txt):
                        rep.warn(pp + ".text", "人物四视图的【版式】第一句要写固定的排列句：四格横向排列，从左到右依次为正面全身、"
                                 "90°侧面全身、背面全身、面部近景（见 asset-character.md）")
                    if "facing" in pr and pr["facing"] not in COMPASS:
                        rep.error(pp + ".facing", "朝向只能写 %s 之一" % "、".join(COMPASS))
                    if scene_role(lab) == "多机位" and txt is not None and "格" in txt:
                        miss = [w for w in ("V1", "不多不少") if w not in txt]
                        if miss:
                            rep.warn(pp + ".text", "场景多机位要写明格数（「共 N 格，不多不少」）并用 V1、V2……标注每个机位"
                                     "（缺「%s」；见 asset-scene.md「场景多机位」）" % "、".join(miss))
                    if "tag" in pr:
                        rep.warn(pp + ".tag", "tag 已不再使用：@图N 由脚本按每个段落的上传顺序生成；已忽略")
            if aid is not None:
                asset_labels[aid] = labels

    # 段落
    segs = data.get("segments")
    if segs is None:
        rep.error("segments", "缺少这个字段")
        return
    if not isinstance(segs, list) or not segs:
        rep.error("segments", "必须是非空列表")
        return

    sec_limit = model_default(model, DEFAULT_MAX_SECONDS, max_seconds)
    img_limit = model_default(model, DEFAULT_MAX_IMAGES, max_images)
    used_ids = set()
    next_shot_no = 1  # 镜头号全片连续

    for i, seg in enumerate(segs):
        p = "segments[%d]" % i
        if not isinstance(seg, dict):
            rep.error(p, "必须是对象")
            continue
        need_text(seg, "title", p, rep)
        need_text(seg, "concept", p, rep)
        snd = need_text(seg, "sound", p, rep)
        if snd is not None and "<" not in snd:
            rep.warn(p + ".sound", "【声音】里的音效没有用半角尖括号 <> 括起来（官方符号：音效用 <>，音乐用（）；见 video-prompt.md 的【声音】）")
        neg = need_text(seg, "negative", p, rep)
        for key, name in BLOCK_FIELDS:
            v = seg.get(key)
            if is_text(v) and v.lstrip().startswith("【%s】" % name):
                rep.warn("%s.%s" % (p, key), "字段里不要再写块名「【%s】」，脚本会自动添加；已自动去掉" % name)
        for key, label in (("concept", "整体概念"), ("cinematography", "摄影与影调"), ("sound", "声音")):
            v = seg.get(key)
            hit = [w for w in INTERNAL_TERMS if is_text(v) and w in v]
            if hit:
                rep.warn("%s.%s" % (p, key), "【%s】里出现了资产阶段的内部术语「%s」，视频模型看不懂：换成画面里的方向和位置（见 video-prompt.md「写法细节」）"
                         % (label, "、".join(hit)))
        for key, label in (("concept", "整体概念"), ("cinematography", "摄影与影调"), ("sound", "声音"),
                           ("negative", "反向限制")):
            v = seg.get(key)
            hw = sorted(set(HALF_WIDTH.findall(v))) if is_text(v) else []
            if hw:
                rep.warn("%s.%s" % (p, key), "【%s】里有半角标点「%s」，请改成全角（，；：？！（）“”）" % (label, "".join(hw)))
            ab = ABSTRACT_CAMERA.search(v) if is_text(v) else None
            if ab:
                rep.warn("%s.%s" % (p, key), "【%s】里写了「%s」：%s" % (label, ab.group(0), ABSTRACT_CAMERA_HINT))
        cine = seg.get("cinematography")
        if is_text(cine) and SCREEN_SIDE.search(cine):
            rep.warn(p + ".cinematography",
                     "【摄影与影调】里写了画面左右：机位一换，同一个光源就可能换到画面另一侧。这里把光源绑在场景实物上"
                     "（「柜台左端的台灯」），画面方向写在每个镜头的「光线：」段里（见 video-prompt.md【摄影与影调】）")
        if neg is not None and NEGATIVE_LEAD not in neg:
            rep.warn(p + ".negative", "没有以「以下内容一律不要出现」开头")
        if neg is not None:
            items = [x for x in re.split(r"[、，,]", neg.split("：", 1)[-1].strip().rstrip("。")) if x.strip()]
            if len(items) > NEGATIVE_MAX_ITEMS:
                rep.warn(p + ".negative", "反向限制有 %d 项，超过 %d 项：只留这一段真有的风险和实际出过的问题"
                         "（见 video-prompt.md【反向限制】）" % (len(items), NEGATIVE_MAX_ITEMS))
        if "cinematography" in seg and not is_text(seg["cinematography"]):
            rep.error(p + ".cinematography", "不需要这个块就删掉字段，写了就不能为空")

        if "refs" in seg:
            rep.warn(p + ".refs", "refs 已不再手写：【参考素材绑定】由脚本按本段的 assets 生成；已忽略")
        extra = seg.get("refs_extra", [])
        if not isinstance(extra, list) or not all(is_text(r) for r in extra):
            rep.error(p + ".refs_extra", "写了就必须是非空文字的列表，用来补充参考视频、参考音频之类的行")

        items = seg.get("assets", [])
        n_images = 0
        readback_ok = True
        if not isinstance(items, list):
            rep.error(p + ".assets", "必须是列表，如 [\"人物1\", \"场景1\"]；没有就写 []")
        else:
            seen = set()
            for k, it in enumerate(items):
                ip = "%s.assets[%d]" % (p, k)
                if isinstance(it, str):
                    aid, use = it, None
                elif isinstance(it, dict) and isinstance(it.get("id"), str):
                    aid, use = it["id"], it.get("use")
                else:
                    rep.error(ip, "必须是资产编号，或 {\"id\":…, \"use\":[提示词名称…]}")
                    continue
                if aid not in asset_labels:
                    rep.error(ip, "引用了不存在的资产编号「%s」" % aid)
                    readback_ok = False
                    continue
                if aid in seen:
                    rep.warn(ip, "资产「%s」在本段重复列出" % aid)
                seen.add(aid)
                used_ids.add(aid)
                labels = asset_labels[aid]
                if use is None:
                    n_images += len(default_labels(labels))
                elif (not isinstance(use, list) or not use or not all(isinstance(u, str) for u in use)):
                    rep.error(ip + ".use", "必须是非空的提示词名称列表，如 [\"母版\", \"反打\", \"俯视图\"]")
                else:
                    bad = [u for u in use if u not in labels]
                    if bad:
                        rep.error(ip + ".use", "资产「%s」没有名为 %s 的提示词，现有：%s"
                                  % (aid, "、".join(bad), "、".join(labels)))
                    n_images += len([lab for lab in labels if lab in use])
        if img_limit is not None and n_images > img_limit:
            rep.warn(p + ".assets",
                     "本段需要上传 %d 张参考图，超过所选版本的默认上限 %d 张（用户的平台数字不同时可忽略）；"
                     "可以拆段，或用 use 只带必要的图" % (n_images, img_limit))

        shots = seg.get("shots")
        if not isinstance(shots, list) or not shots:
            rep.error(p + ".shots", "缺少，或不是非空列表（每项 {title, body}）")
            continue
        prev_end = 0.0
        prompt_chars = sum(len(re.sub(r"\s+", "", seg.get(k) or "")) for k in ("concept", "sound", "negative")
                           if isinstance(seg.get(k), str))
        texts_with_refs = [seg.get(k) for k in ("concept", "cinematography", "sound") if is_text(seg.get(k))]
        texts_with_refs += [r for r in extra if is_text(r)] if isinstance(extra, list) else []
        for j, sh in enumerate(shots):
            sp = "%s.shots[%d]" % (p, j)
            if not isinstance(sh, dict):
                rep.error(sp, "必须是 {\"title\":…, \"body\":…}")
                continue
            t = need_text(sh, "title", sp, rep)
            body_txt = need_text(sh, "body", sp, rep)
            hit = [w for w in INTERNAL_TERMS if body_txt is not None and w in body_txt]
            if hit:
                rep.warn(sp + ".body", "正文里出现了资产阶段的内部术语「%s」，视频模型看不懂：换成画面里的方向和位置（见 video-prompt.md「写法细节」）" % "、".join(hit))
            if body_txt is not None:
                prompt_chars += len(re.sub(r"\s+", "", body_txt.split(LIGHT_LEAD)[0]))
                texts_with_refs.append(body_txt)
            need_text(sh, "camera", sp, rep)
            need_text(sh, "summary", sp, rep)
            lines_txt = need_text(sh, "lines", sp, rep)
            if lines_txt is not None and re.search(r"[\"“”「」]", lines_txt):
                rep.warn(sp + ".lines", "台词列只写「无」或「谁说、几个字」，不要抄台词原文（台词原文只在正文里写一次）")
            if t is None:
                continue
            m = SHOT_TITLE_RE.match(t.strip())
            if not m:
                rep.warn(sp + ".title",
                         "标题行格式应为「镜头1｜内景｜0-5秒｜中景」（全角竖线），现在是「%s」" % t)
                prev_end = None
                next_shot_no += 1
                continue
            no = int(m.group(1))
            if (is_text(lines_txt) and lines_txt.strip() != "无" and body_txt is not None
                    and "（" not in body_txt):
                rep.warn(sp + ".body",
                         "镜头%d 有台词，但没有按「角色（语气）……说：“台词”」写出语气（括号里不超过 3 个词，不能省）" % no)
            if body_txt is not None:
                vague = VAGUE_DIRECTION.search(body_txt)
                if vague:
                    rep.warn(sp + ".body", "镜头%d 写了「%s」这类方向：模型不知道是谁的方向，常常直接理解成画面左右。"
                             "改成画面里的方向（画面左侧、画面右侧、靠近或远离镜头、画面上方）（见 video-prompt.md「写法细节」）"
                             % (no, vague.group(0)))
                ab = ABSTRACT_CAMERA.search(body_txt)
                if ab:
                    rep.warn(sp + ".body", "镜头%d 写了「%s」：%s" % (no, ab.group(0), ABSTRACT_CAMERA_HINT))
                if genre == "影视" and LIGHT_LEAD not in body_txt:
                    rep.warn(sp + ".body", "镜头%d 没有「光线：」段：影视体裁每个镜头另起一段，写光落在脸和手的哪一边、背景多亮；"
                             "有明确光源时按这一镜的机位写光从画面哪一侧来，阴天这类漫射光写上方柔光和哪边被遮挡稍暗（见 video-prompt.md【分镜】）" % no)
                if m.group(5).strip() in CLOSE_SIZES and not CLOSE_POSITION.search(body_txt.split(LIGHT_LEAD)[0]):
                    rep.warn(sp + ".body", "镜头%d 是%s，但没有写人物偏画面哪一侧、视线看向哪一侧（例如「看向画面左侧外」）；物品特写写「画面里只有……」或「一只手从画面左侧伸进来」。"
                             "切镜头后人物和物品的左右关系容易乱（见 video-prompt.md「在场的人不凭空消失」）" % (no, m.group(5).strip()))
                again = restated_quote(body_txt)
                if again is not None:
                    rep.warn(sp + ".body",
                             "镜头%d 在台词说完后又复述了台词里的字「%s」：语气、表情、动作放到台词前面写"
                             "（官方提示：台词后复述再追加描述，容易让模型生成字幕；见 video-prompt.md 的台词规则）" % (no, again))
            if is_text(lines_txt) and body_txt is not None:
                claimed = [int(n) for n in re.findall(r"(\d+)\s*字", lines_txt)]
                quotes = QUOTE_RE.findall(body_txt)
                if claimed and quotes:
                    actual = sum(len(quote_chars(q)) for q in quotes)
                    if abs(sum(claimed) - actual) > 1:
                        rep.warn(sp + ".lines", "镜头%d 的台词列写了 %d 字，正文里的台词实际是 %d 字（字数不含标点）"
                                 % (no, sum(claimed), actual))
            hw = sorted(set(HALF_WIDTH.findall(body_txt))) if body_txt is not None else []
            if hw:
                rep.warn(sp + ".body", "镜头%d 的正文里有半角标点「%s」，请改成全角（，；：？！（）“”）" % (no, "".join(hw)))
            if no != next_shot_no:
                rep.warn(sp + ".title", "镜头号应全片连续：这里应是镜头%d，现在是镜头%d" % (next_shot_no, no))
            next_shot_no = no + 1
            start, end = float(m.group(3)), float(m.group(4))
            if "." in m.group(3) + m.group(4):
                rep.warn(sp + ".title", "时间段请用整数秒（Seedance 2.5 只认整数秒的时间戳；见 models.md）")
            if prev_end is not None and abs(start - prev_end) > 1e-6:
                rep.warn(sp + ".title", "起始秒数 %g 和上一个镜头的结束 %g 不连续" % (start, prev_end))
            if end <= start:
                rep.error(sp + ".title", "结束时间 %g 不晚于起始时间 %g：时间段写反了或写错了" % (end, start))
            elif body_txt is not None:
                spoken = sum(len(quote_chars(q)) for q in QUOTE_RE.findall(body_txt))
                if spoken and spoken / (end - start) > SPEECH_MAX_RATE:
                    rep.warn(sp + ".body",
                             "镜头%d 的台词共 %d 字、%g 秒，约 %.1f 字/秒，超过 %g 字/秒：除了争吵、慌乱、抢话，基本说不完。"
                             "先延长这个镜头，或在台词的自然停顿处拆开；不要删台词，要缩短先问用户（见 storyboard.md「台词与时长」）"
                             % (no, spoken, end - start, spoken / (end - start), SPEECH_MAX_RATE))
            prev_end = end
        if prev_end is not None and sec_limit is not None and prev_end > sec_limit:
            rep.warn(p + ".shots",
                     "总时长约 %g 秒，超过所选版本的默认上限 %d 秒（用户的平台数字不同时可忽略）" % (prev_end, sec_limit))
        if prev_end is not None and prev_end > 0:
            limit = max(PROMPT_CHARS_PER_15S, PROMPT_CHARS_PER_15S * prev_end / 15.0 * 0.75)
            if prompt_chars > limit:
                rep.warn(p + ".shots",
                         "提示词约 %d 字（不算参考素材绑定、【摄影与影调】和「光线：」段），超过提醒线约 %d 字：先删重复（同一件事说了两遍、"
                         "参考图里已有的东西、正文写过又在反向限制里反着写），还超就在镜头之间拆段。不要为了压字数删关键动作、台词、"
                         "站位机位和光线段（见 video-prompt.md「每个镜头写到什么程度」）" % (prompt_chars, limit))
        if n_images:
            bad_refs = sorted({int(x) for t in texts_with_refs for x in IMG_REF.findall(t) if int(x) > n_images or int(x) == 0})
            if bad_refs:
                rep.warn(p, "提示词里写了 %s，但本段只上传 %d 张图：编号要和本段上传顺序一一对应（见 video-prompt.md【参考素材绑定】）"
                         % ("、".join("@图%d" % x for x in bad_refs), n_images))

        for key in ("blocking", "readback"):
            if key in seg and not check_layout_schema(seg[key], "%s.%s" % (p, key), rep):
                readback_ok = False
        if readback_ok and ("blocking" in seg or "readback" in seg) and isinstance(data.get("assets"), list):
            for path, msg in readback_findings(seg, assets_by_id(data), p):
                rep.warn(path, msg)

    for aid in asset_labels:
        if aid not in used_ids:
            rep.warn("assets", "资产「%s」没有被任何段落使用" % aid)


# ---------------------------------------------------------------- 回读调度图（见 references/readback.md）


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pt(v):
    return isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v)


def check_layout_schema(d, p, rep):
    """blocking / readback 的格式：坐标都是数字，摄影机有 look。格式不对报错误，不生成。"""
    ok = True
    def bad(path, msg):
        nonlocal ok
        ok = False
        rep.error(path, msg)
    if not isinstance(d, dict):
        bad(p, "必须是对象，格式见 references/readback.md")
        return False
    for k, o in enumerate(d.get("objects", []) or []):
        if not (isinstance(o, dict) and is_text(o.get("name")) and all(_num(o.get(x)) for x in ("x", "y", "w", "h"))):
            bad("%s.objects[%d]" % (p, k), "固定物要写 name、x、y、w、h（数字）")
    shots = d.get("shots")
    if not isinstance(shots, list) or not shots:
        bad(p + ".shots", "缺少，或不是非空列表")
        return False
    for j, sh in enumerate(shots):
        sp = "%s.shots[%d]" % (p, j)
        if not isinstance(sh, dict) or not isinstance(sh.get("shot"), int):
            bad(sp, "每项要有 shot（全片镜头号，整数）")
            continue
        cam = sh.get("camera")
        if not (isinstance(cam, dict) and _num(cam.get("x")) and _num(cam.get("y")) and _pt(cam.get("look"))):
            bad(sp + ".camera", "摄影机要写 x、y 和 look:[x, y]（它朝着的点）")
        for k, pe in enumerate(sh.get("people", []) or []):
            if not (isinstance(pe, dict) and is_text(pe.get("name")) and _num(pe.get("x")) and _num(pe.get("y"))):
                bad("%s.people[%d]" % (sp, k), "人物要写 name、x、y")
        for k, pr in enumerate(sh.get("props", []) or []):
            if not (isinstance(pr, dict) and is_text(pr.get("name")) and _num(pr.get("x")) and _num(pr.get("y"))
                    and ("front" not in pr or _pt(pr.get("front")))):
                bad("%s.props[%d]" % (sp, k), "道具要写 name、x、y，有正反面的写 front:[x, y]")
    return ok


def bearing(dx, dy):
    return math.degrees(math.atan2(dx, dy)) % 360


def angle_gap(a, b):
    g = abs(a - b) % 360
    return min(g, 360 - g)


def screen_side(cam, x, y):
    """从摄影机朝 look 看，这个点在画面哪边：左、右、中、画外、背后。"""
    dx, dy = cam["look"][0] - cam["x"], cam["look"][1] - cam["y"]
    vx, vy = x - cam["x"], y - cam["y"]
    cross, dot = dx * vy - dy * vx, dx * vx + dy * vy
    if dot <= 0:
        return "背后"
    ang = math.degrees(math.atan2(cross, dot))
    if abs(ang) > FOV_HALF:
        return "画外"
    if abs(ang) < 4:
        return "中"
    return "左" if ang > 0 else "右"


def prop_face(cam, pr):
    """有正反面的道具，摄影机看到的是哪一面。"""
    fx, fy = pr["front"][0] - pr["x"], pr["front"][1] - pr["y"]
    cx, cy = cam["x"] - pr["x"], cam["y"] - pr["y"]
    nf, nc = math.hypot(fx, fy), math.hypot(cx, cy)
    if nf == 0 or nc == 0:
        return "侧面"
    c = (fx * cx + fy * cy) / (nf * nc)
    return "正面" if c > 0.5 else ("背面" if c < -0.5 else "侧面")


def layout_objects(seg):
    for key in ("readback", "blocking"):
        objs = (seg.get(key) or {}).get("objects")
        if objs:
            return objs
    return []


def shot_facts(sh):
    cam = sh["camera"]
    sides = {pe["name"]: screen_side(cam, pe["x"], pe["y"]) for pe in sh.get("people", []) or []}
    faces = {pr["name"]: prop_face(cam, pr) for pr in sh.get("props", []) or [] if "front" in pr}
    return sides, faces, bearing(cam["look"][0] - cam["x"], cam["look"][1] - cam["y"])


def readback_findings(seg, assets, p):
    """回读核对：文字自相矛盾、和调度底稿不一致、没写清、缺图。返回 [(路径, 说明)]。"""
    out = []
    rb, bk = seg.get("readback"), seg.get("blocking")
    objs = layout_objects(seg)
    xs = [o["x"] for o in objs] or [0]
    ys = [o["y"] for o in objs] or [0]
    span = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 4.0)
    plan = {sh["shot"]: sh for sh in (bk or {}).get("shots", [])}
    if rb:
        if isinstance(rb.get("rounds"), int) and rb["rounds"] > 3:
            out.append((p + ".readback.rounds", "回读已经第 %d 轮：三轮还对不上，多半是调度底稿本身走不通，停下来把差异给用户看、问怎么改" % rb["rounds"]))
        for j, sh in enumerate(rb["shots"]):
            sp = "%s.readback.shots[%d]" % (p, j)
            no = sh["shot"]
            sides, faces, brg = shot_facts(sh)
            for un in sh.get("unclear", []) or []:
                out.append((sp, "镜头%d 提示词没写清：%s" % (no, un)))
            claim = sh.get("screen") or {}
            for side in ("左", "右"):
                for name in claim.get(side, []) or []:
                    got = sides.get(name)
                    if got is None:
                        out.append((sp, "镜头%d 文字写%s在画面%s侧，但回读不出%s站在哪" % (no, name, side, name)))
                    elif got in ("画外", "背后"):
                        out.append((sp, "镜头%d 文字写%s在画面%s侧，按文字写的机位和站位，%s在%s（自相矛盾）" % (no, name, side, name, got)))
                    elif got != "中" and got != side:
                        out.append((sp, "镜头%d 文字写%s在画面%s侧，按文字写的机位和站位，%s在画面%s侧（自相矛盾）" % (no, name, side, name, got)))
            for name in claim.get("画外", []) or []:
                if sides.get(name) in ("左", "右", "中"):
                    out.append((sp, "镜头%d 文字写%s不入画，按文字写的位置他在画面里（要给他一个去处，或换机位）" % (no, name)))
            for name, face in (sh.get("faces") or {}).items():
                got = faces.get(name)
                if got and face in ("正面", "背面") and got != face:
                    out.append((sp, "镜头%d 文字写%s画面里看到%s，按文字写的机位和朝向看到的是%s（自相矛盾）" % (no, name, face, got)))
            ref = plan.get(no)
            if ref is None:
                continue
            psides, pfaces, pbrg = shot_facts(ref)
            if angle_gap(brg, pbrg) > 45:
                out.append((sp, "镜头%d 回读的摄影机朝向和调度底稿差约 %.0f°" % (no, angle_gap(brg, pbrg))))
            dist = math.hypot(sh["camera"]["x"] - ref["camera"]["x"], sh["camera"]["y"] - ref["camera"]["y"])
            if dist > max(1.5, 0.25 * span):
                out.append((sp, "镜头%d 回读的摄影机位置和调度底稿差约 %.1f 米" % (no, dist)))
            for name, ps in psides.items():
                got = sides.get(name)
                inf = lambda v: v in ("左", "右", "中")
                if got is None:
                    if inf(ps):
                        out.append((sp, "镜头%d 调度底稿里%s在画面里，回读不出他" % (no, name)))
                elif inf(ps) != inf(got) or (ps in ("左", "右") and got in ("左", "右") and ps != got):
                    out.append((sp, "镜头%d %s：调度底稿是%s，按提示词回读是%s" % (no, name, ps, got)))
            for name in sides:
                if name not in psides and sides[name] in ("左", "右", "中"):
                    out.append((sp, "镜头%d 回读出调度底稿里没有的人：%s" % (no, name)))
            for name, pf in pfaces.items():
                if name in faces and faces[name] != pf:
                    out.append((sp, "镜头%d %s：调度底稿看到%s，按提示词回读看到%s" % (no, name, pf, faces[name])))
    # 缺图：镜头朝的方向要有方向图；上传了的方向图要有镜头用到
    src = rb or bk
    if src and assets:
        facings = []
        for n, a, pr in seg_upload(seg, assets):
            if a["kind"] == "场景" and scene_role(pr["label"]) in DIRECTION_ROLES and pr.get("facing") in COMPASS:
                facings.append((pr["label"], a["name"], COMPASS[pr["facing"]]))
        if facings:
            brgs = []
            for sh in src["shots"]:
                b = shot_facts(sh)[2]
                brgs.append(b)
                if not any(angle_gap(b, f) <= FACING_TOLERANCE for _, _, f in facings):
                    out.append(("%s.assets" % p, "镜头%d 摄影机朝向约 %.0f°（北 0、东 90），本段上传的场景图里没有这个方向：缺图，补一张这个方向的角度图，不要为了省图改机位"
                                % (sh["shot"], b)))
            for lab, name, f in facings:
                if not any(angle_gap(b, f) <= FACING_TOLERANCE for b in brgs):
                    out.append(("%s.assets" % p, "本段上传了%s的「%s」，但没有镜头朝这个方向拍：不传这张，也不要为了用上它加镜头" % (name, lab)))
    return out


def layout_svg(sh, objs, title):
    """一个镜头的小平面图：固定物、人物、摄影机和视野、道具正面。北在上。"""
    pts = [(o["x"] - o["w"] / 2, o["y"] - o["h"] / 2) for o in objs] + [(o["x"] + o["w"] / 2, o["y"] + o["h"] / 2) for o in objs]
    pts += [(pe["x"], pe["y"]) for pe in sh.get("people", []) or []] + [(sh["camera"]["x"], sh["camera"]["y"])]
    pts += [(pr["x"], pr["y"]) for pr in sh.get("props", []) or []]
    x0, x1 = min(x for x, _ in pts) - LAYOUT_PAD_M, max(x for x, _ in pts) + LAYOUT_PAD_M
    y0, y1 = min(y for _, y in pts) - LAYOUT_PAD_M, max(y for _, y in pts) + LAYOUT_PAD_M
    size, top = LAYOUT_WIDTH, LAYOUT_TITLE_H
    k = size / max(x1 - x0, y1 - y0)
    X = lambda x: (x - x0) * k
    Y = lambda y: top + (y1 - y) * k
    h = top + (y1 - y0) * k + LAYOUT_SCALEBAR_H
    el = ['<svg class="layout" viewBox="0 0 %.0f %.0f" width="%.0f" height="%.0f" role="img" aria-label="%s">'
          % (size, h, size, h, esc(title)),
          '<text x="2" y="12" font-size="11" fill="currentColor">%s</text>' % esc(title),
          '<text x="%.0f" y="12" font-size="10" fill="currentColor" opacity=".6" text-anchor="end">北↑</text>' % (size - 2)]
    for o in objs:
        el.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="currentColor" stroke-opacity=".45"/>'
                  % (X(o["x"] - o["w"] / 2), Y(o["y"] + o["h"] / 2), o["w"] * k, o["h"] * k))
        small = o["w"] * k < 9 * len(o["name"]) + 4 or o["h"] * k < 14
        ly = Y(o["y"] - o["h"] / 2) + 10 if small else Y(o["y"]) + 3   # 小物件的名字写在矩形下方
        el.append('<text class="lbl" x="%.1f" y="%.1f" font-size="9" fill="currentColor" opacity=".7" text-anchor="middle">%s</text>'
                  % (X(o["x"]), ly, esc(o["name"])))
    cam = sh["camera"]
    b = math.radians(bearing(cam["look"][0] - cam["x"], cam["look"][1] - cam["y"]))
    L = max(x1 - x0, y1 - y0) * 0.6
    for d in (-LAYOUT_FOV_DRAW, LAYOUT_FOV_DRAW):
        a = b + math.radians(d)
        el.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c2410c" stroke-dasharray="3 3"/>'
                  % (X(cam["x"]), Y(cam["y"]), X(cam["x"] + L * math.sin(a)), Y(cam["y"] + L * math.cos(a))))
    tri = []
    for d, r in ((0, 0.5), (140, 0.35), (-140, 0.35)):
        a = b + math.radians(d)
        tri.append("%.1f,%.1f" % (X(cam["x"] + r * math.sin(a)), Y(cam["y"] + r * math.cos(a))))
    el.append('<polygon points="%s" fill="#c2410c"/>' % " ".join(tri))
    for pr in sh.get("props", []) or []:
        el.append('<rect x="%.1f" y="%.1f" width="5" height="5" fill="#2563eb"/>' % (X(pr["x"]) - 2.5, Y(pr["y"]) - 2.5))
        if "front" in pr:
            el.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#2563eb"/>'
                      % (X(pr["x"]), Y(pr["y"]), X(pr["x"]) + (pr["front"][0] - pr["x"]) * k * 0.4,
                         Y(pr["y"]) - (pr["front"][1] - pr["y"]) * k * 0.4))
        el.append('<text class="lbl" x="%.1f" y="%.1f" font-size="9" fill="#2563eb">%s</text>' % (X(pr["x"]) + 4, Y(pr["y"]) + 9, esc(pr["name"])))
    for pe in sh.get("people", []) or []:
        el.append('<circle cx="%.1f" cy="%.1f" r="4" fill="currentColor"/>' % (X(pe["x"]), Y(pe["y"])))
        el.append('<text class="lbl" x="%.1f" y="%.1f" font-size="10" font-weight="600" fill="currentColor" text-anchor="end">%s</text>'
                  % (X(pe["x"]) - 5, Y(pe["y"]) - 4, esc(pe["name"])))
    # 比例尺：取 1、2、5、10 米里画出来最接近画布四分之一宽的那个
    bar = min((1, 2, 5, 10, 20), key=lambda m: abs(m * k - size / 4))
    by = h - 5
    el.append('<line x1="4" y1="%.1f" x2="%.1f" y2="%.1f" stroke="currentColor" stroke-width="2"/>' % (by, 4 + bar * k, by))
    el.append('<text x="%.1f" y="%.1f" font-size="9" fill="currentColor" opacity=".7">%d 米</text>' % (8 + bar * k, by + 3, bar))
    el.append("</svg>")
    return "".join(el)


def sides_text(sh):
    sides, faces, _ = shot_facts(sh)
    parts = ["%s：%s" % (n, s) for n, s in sides.items()]
    parts += ["%s看到%s" % (n, f) for n, f in faces.items()]
    return "；".join(parts) or "画面里没有人"


def layout_html(seg, assets, p):
    rb, bk = seg.get("readback"), seg.get("blocking")
    if not rb and not bk:
        return ""
    objs = layout_objects(seg)
    out = ['<h4>调度图</h4><div class="hint">每个镜头一个平面图，北在上；红色三角是摄影机，虚线是大致视野；'
           '蓝色小方块是道具，短线指向它的正面。%s只做平面粗算，不管高低和遮挡（见 references/readback.md）。</div>'
           % ("上排是调度底稿，下排是只拿提示词文字回读出来的。" if rb and bk else
              ("这是只拿提示词文字回读出来的。" if rb else "这是调度底稿，还没有按提示词回读。"))]
    for key, name in (("blocking", "调度底稿"), ("readback", "按提示词回读")):
        d = seg.get(key)
        if not d:
            continue
        label = name + ("（第 %d 轮）" % d["rounds"] if key == "readback" and isinstance(d.get("rounds"), int) else "")
        out.append('<div class="layout-row"><div class="layout-label">%s</div>' % esc(label))
        for sh in d["shots"]:
            out.append('<figure class="layout-cell">%s<figcaption>%s</figcaption></figure>'
                       % (layout_svg(sh, objs, "镜头%d" % sh["shot"]), esc(sides_text(sh))))
        out.append("</div>")
    found = readback_findings(seg, assets, p)
    if found:
        out.append('<div class="hint"><strong>核对没通过</strong>：%s</div>'
                   % "<br>".join(esc(m) for _, m in found))
    else:
        out.append('<div class="hint"><strong>核对通过</strong>：%s</div>'
                   % ("回读和调度底稿一致，文字没有自相矛盾，镜头朝的方向都有图。" if rb and bk else "没有发现自相矛盾和缺图。"))
    return "\n".join(out)


def layout_md(seg, assets, p):
    rb, bk = seg.get("readback"), seg.get("blocking")
    if not rb and not bk:
        return []
    out = ["**调度图核对**（Markdown 版不画图，只列算出来的画面左右）", ""]
    for key, name in (("blocking", "调度底稿"), ("readback", "按提示词回读")):
        d = seg.get(key)
        if d:
            out += ["- %s：%s" % (name, "　".join("镜头%d（%s）" % (sh["shot"], sides_text(sh)) for sh in d["shots"]))]
    found = readback_findings(seg, assets, p)
    out += ["- 核对：" + ("；".join(m for _, m in found) if found else "通过"), ""]
    return out


# ---------------------------------------------------------------- 数据整理


def seg_items(seg):
    """本段用到的资产：[(资产编号, use 或 None)]，保持写的顺序。"""
    out = []
    for it in seg.get("assets", []):
        if isinstance(it, str):
            out.append((it, None))
        else:
            out.append((it["id"], it.get("use")))
    return out


def seg_upload(seg, assets):
    """本段的上传顺序 [(编号N, 资产, 提示词)]：先人物，再场景等；每一类按写的顺序。
    @图N 就是这个顺序，每个段落从 1 重新编号。"""
    people, others = [], []
    for aid, use in seg_items(seg):
        a = assets[aid]
        keep = default_labels([pr["label"] for pr in a["prompts"]]) if use is None else use
        for p in a["prompts"]:
            if p["label"] in keep:
                (people if a["kind"] == "人物" else others).append((a, p))
    return [(i + 1, a, p) for i, (a, p) in enumerate(people + others)]


def ref_line(n, a, p, n_scenes):
    """【参考素材绑定】里的一行：这张图是什么、参考什么、不参考什么。

    官方提示词指南要求写清每个素材的编号和用途；只参考一部分时，写明参考哪一部分。
    """
    kind, label, name = a["kind"], p["label"], a["name"]
    if kind == "人物":
        if label in CHARACTER_SHEET_LABELS:
            return "@图%d 是%s：只参考长相、发型和服装，画面里只有一个%s。" % (n, name, name)
        if "四格" in p.get("text", ""):
            # 状态版也画成四格时，模型可能当成四个人，绑定行要写明
            return "@图%d 是%s（%s）：四格是同一个人；只参考长相、发型和服装，画面里只有一个%s。" % (n, name, label, name)
        return "@图%d 是%s（%s）：只参考长相、发型和服装，画面里只有一个%s。" % (n, name, label, name)
    if kind == "场景":
        where = name if n_scenes > 1 else "这个场景"
        role = scene_role(label)
        if role == "斜俯视":
            return "@图%d 是%s的45°俯视全景：只参考空间布局、远近和高低，不是镜头角度。" % (n, where)
        if role == "反打":
            return "@图%d 是%s的反向回望：从主图的另一头往回看，参考这一面的空间、陈设和光线，不是分镜。" % (n, where)
        if role == "角度":
            note = label[len(ANGLE_LABEL):].lstrip("·:：- （(").rstrip("）)")
            what = "另一个方向（%s）" % note if note else "另一个方向"
            return "@图%d 是%s的%s：只参考从这个方向看过去的空间，不是分镜。" % (n, where, what)
        if role == "主图":
            return "@图%d 是%s的主图：参考空间布局、材质和光线。" % (n, where)
        if role == "多机位":
            return "@图%d 是%s的其他角度：只参考空间，不是分镜；图上的标注不进画面。" % (n, where)
        if role == "俯视图":
            # 俯视图可能被转了 90°（场景的长边沿画面横向），提醒模型别拿图的上下当前后
            return "@图%d 是%s的正俯视平面图：只参考空间布局，不是镜头角度；图可能转过方向，前后左右以门窗和家具为准。" % (n, where)
        if role == "人物走位":
            return ("@图%d 是%s的走位示意图：只参考空间和人物路线；"
                    "线条、箭头、字母和标注不进画面。" % (n, where))
        return "@图%d 是%s的%s：参考空间布局。" % (n, where, label)
    if kind == "参考帧":
        if label in STATE_FRAME_LABELS:
            # 只写文字带不过去的外观；左右、朝向、手的动作写在镜头正文里（机位可能已经换到人物连线的另一边）
            return ("@图%d 是上一段最后一帧：只参考人物的服装、发型和身上的状态（湿润、泪痕、污渍）；"
                    "不是首帧，不照搬构图，人物左右以本段文字为准。" % n)
        return "@图%d 为首帧：本段从这一帧开始（上一段视频的最后一帧）。" % n
    if kind == "道具":
        return "@图%d 是%s（%s）：只参考外观和材质，画面里只有一个%s。" % (n, name, label, name)
    return "@图%d 是%s（%s）：只参考外观。" % (n, name, label)


def seg_refs(seg, assets):
    """【参考素材绑定】的各行：按本段的上传顺序，每张图一行，写清它是什么、参考什么。"""
    upload = seg_upload(seg, assets)
    n_scenes = len({a["id"] for n, a, p in upload if a["kind"] == "场景"})
    lines = [ref_line(n, a, p, n_scenes) for n, a, p in upload]
    lines.extend(r.strip() for r in seg.get("refs_extra", []))
    return lines


def upload_text(seg, assets):
    """给人看的上传顺序：图1 阿杰·人物四视图；图2 …"""
    return "；".join("图%d %s·%s" % (n, a["name"], p["label"]) for n, a, p in seg_upload(seg, assets))


def seg_duration(seg):
    """从最后一个镜头的标题行取这个段落的总秒数；取不到返回 None。"""
    for sh in reversed(seg["shots"]):
        m = SHOT_TITLE_RE.match(sh["title"].strip())
        if m:
            return float(m.group(4))
    return None


def fmt_seconds(v):
    if v is None:
        return "—"
    return ("%g" % v) + " 秒"


def shot_range(seg):
    nums = []
    for sh in seg["shots"]:
        m = SHOT_TITLE_RE.match(sh["title"].strip())
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return "%d 个镜头" % len(seg["shots"])
    if len(nums) == 1 or nums[0] == nums[-1]:
        return "镜头%d" % nums[0]
    return "镜头%d–%d" % (nums[0], nums[-1])


SHOT_TABLE_HEAD = ("镜号", "内外景", "景别", "机位与运动", "画面要点", "台词", "时间")


def shot_cells(sh):
    """镜头速览表的一行：镜号、内外景、景别、时间来自标题行，其余三列是写的。"""
    m = SHOT_TITLE_RE.match(sh["title"].strip())
    if m:
        no, io, size = "镜头%s" % m.group(1), m.group(2), m.group(5).strip()
        time = "%s-%s秒" % (m.group(3), m.group(4))
    else:
        no, io, size, time = sh["title"].strip(), "—", "—", "—"
    return [no, io, size, sh["camera"].strip(), sh["summary"].strip(), sh["lines"].strip(), time]


def compose_video_prompt(seg, assets):
    """按固定顺序把各块拼成一份视频提示词（台词只在【分镜】里出现一次）。"""
    refs = seg_refs(seg, assets) or ["本段没有参考图"]
    parts = ["【整体概念】\n" + strip_block_name(seg["concept"], "整体概念"),
             "【参考素材绑定】\n" + "\n".join(refs)]
    if seg.get("cinematography"):
        parts.append("【摄影与影调】\n" + strip_block_name(seg["cinematography"], "摄影与影调"))
    shots = "\n\n".join(sh["title"].strip() + "\n" + sh["body"].strip() for sh in seg["shots"])
    parts.append("【分镜】\n" + shots)
    parts.append("【声音】\n" + strip_block_name(seg["sound"], "声音"))
    parts.append("【反向限制】\n" + strip_block_name(seg["negative"], "反向限制"))
    return "\n\n".join(parts)


def assets_by_id(data):
    return {a["id"]: a for a in data["assets"]}


def used_in(data, aid):
    """用到这个资产的段落序号（从 1 起）。"""
    return [i + 1 for i, seg in enumerate(data["segments"]) if any(x == aid for x, _ in seg_items(seg))]


def used_in_text(data, aid):
    return "、".join(seg_name(n) for n in used_in(data, aid)) or "未使用"


def needs_text(seg, assets):
    names = []
    for aid, _ in seg_items(seg):
        a = assets[aid]
        names.append("%s（%s）" % (a["name"], a["kind"]))
    return "、".join(names) or "—"


def asset_images_text(a):
    return "、".join(pr["label"] for pr in a["prompts"])


# ---------------------------------------------------------------- HTML


def esc(s):
    return html.escape(s, quote=True)


SEP_ROW_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rich(s):
    """转义后，把 **加粗** 渲染成粗体（其他 Markdown 不渲染）。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))


def render_text(text):
    """段落保持换行；连续以 | 开头的行渲染成表格。"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip("\n")):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        if all(ln.lstrip().startswith("|") for ln in lines):
            rows = [ln for ln in lines if not (SEP_ROW_RE.match(ln) and "-" in ln)]
            if rows:
                head, body = split_row(rows[0]), [split_row(r) for r in rows[1:]]
                h = "<table><thead><tr>%s</tr></thead>" % "".join("<th>%s</th>" % rich(c) for c in head)
                b = "<tbody>%s</tbody></table>" % "".join(
                    "<tr>%s</tr>" % "".join("<td>%s</td>" % rich(c) for c in r) for r in body)
                out.append(h + b)
                continue
        out.append('<div class="txt">%s</div>' % rich(block.strip("\n")))
    return "\n".join(out)


def copy_block(dom_id, title, text):
    return (
        '<div class="block"><div class="block-head"><span>%s</span>'
        '<button type="button" class="copy" data-target="%s">复制</button></div>'
        '<pre class="prompt" id="%s">%s</pre></div>'
        % (esc(title), dom_id, dom_id, esc(text))
    )


def shot_table_html(seg):
    head = "".join("<th>%s</th>" % esc(h) for h in SHOT_TABLE_HEAD)
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(c) for c in shot_cells(sh)) for sh in seg["shots"])
    return '<table class="overview"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, rows)


def build_html(data):
    assets = assets_by_id(data)
    segs = data["segments"]
    script = normalize_script(data["script"])

    # 顶栏
    meta = ('<span class="project">%s</span>'
            '<span class="tag">%s</span><span class="tag">画幅 %s</span><span class="tag">%s</span>'
            '<span class="tag">导演手册 skill %s · 生成于 %s</span>'
            % (esc(data["project"]), esc(data["genre"]), esc(data["ratio"]), esc(data["model"]),
               esc(skill_version()), date.today().isoformat()))

    # 导航：剧本、分镜、资产提示词（各资产）、视频提示词（各段）
    nav = ['<a class="top-item" href="#script">剧本</a>',
           '<a class="top-item" href="#storyboard">分镜</a>',
           '<a class="top-item" href="#assets">资产提示词</a>']
    for i, a in enumerate(data["assets"]):
        nav.append('<a class="sub-item" href="#asset-%d">%s · %s</a>' % (i, esc(a["id"]), esc(a["name"])))
    nav.append('<a class="top-item" href="#video">视频提示词</a>')
    for i, seg in enumerate(segs):
        nav.append('<a class="sub-item" href="#vp-%d">%s · %s</a>' % (i + 1, seg_name(i + 1), esc(seg["title"])))

    body = []

    # 剧本
    body.append('<section class="part" id="script"><h2>剧本</h2>')
    for sec in script:
        body.append('<div class="card"><h3 style="margin-top:0">%s</h3>%s</div>'
                    % (esc(sec["title"]), render_text(sec["body"])))
    body.append("</section>")

    # 分镜
    body.append('<section class="part" id="storyboard"><h2>分镜</h2>')
    body.append("<h3>片段划分</h3><table><thead><tr><th>段落</th><th>场景</th><th>镜头</th>"
                "<th>总时长</th><th>需要的参考图</th></tr></thead><tbody>")
    for i, seg in enumerate(segs):
        body.append("<tr><td><a href=\"#vp-%d\">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (i + 1, seg_name(i + 1), esc(seg["title"]), esc(shot_range(seg)),
                       esc(fmt_seconds(seg_duration(seg))), esc(needs_text(seg, assets))))
    body.append("</tbody></table>")
    for i, seg in enumerate(segs):
        body.append("<h3>%s · %s</h3>" % (seg_name(i + 1), esc(seg["title"])))
        body.append(shot_table_html(seg))
        for sh in seg["shots"]:
            body.append('<div class="card shot"><div class="shot-title">%s</div>'
                        '<div class="shot-body">%s</div></div>'
                        % (esc(sh["title"].strip()), esc(sh["body"].strip())))
        lay = layout_html(seg, assets, "segments[%d]" % i)
        if lay:
            body.append(lay)
    body.append("</section>")

    # 资产提示词：所有资产集中在这一节，每个资产只出现一次
    body.append('<section class="part" id="assets"><h2>资产提示词</h2>')
    if data["assets"]:
        body.append("<h3>资产编号表</h3><table><thead><tr><th>编号</th><th>名称</th><th>类型</th>"
                    "<th>图</th><th>用于</th></tr></thead><tbody>")
        for i, a in enumerate(data["assets"]):
            used = "、".join('<a href="#vp-%d">%s</a>' % (n, seg_name(n)) for n in used_in(data, a["id"])) or "未使用"
            body.append("<tr><td><a href=\"#asset-%d\">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                        % (i, esc(a["id"]), esc(a["name"]), esc(a["kind"]), esc(asset_images_text(a)),
                           used))
        body.append("</tbody></table>")
        body.append('<div class="hint">先在这里生成所有资产图，再到下面「视频提示词」里，'
                    "按每一段的「本段上传顺序」把图传给平台。</div>")
        for i, a in enumerate(data["assets"]):
            body.append('<div class="card asset" id="asset-%d">' % i)
            body.append('<div class="seg-head"><span class="seg-title">%s · %s</span>'
                        '<span class="seg-meta">%s · 用于%s</span></div>'
                        % (esc(a["id"]), esc(a["name"]), esc(a["kind"]), esc(used_in_text(data, a["id"]))))
            for j, pr in enumerate(a["prompts"]):
                if a["kind"] == "参考帧":
                    body.append('<div class="hint"><strong>%s</strong>（不是提示词，不用生成）：%s</div>'
                                % (esc(pr["label"]), esc(pr["text"].strip())))
                else:
                    body.append(copy_block("p-a%d-%d" % (i, j), pr["label"], pr["text"].strip()))
            body.append("</div>")
    else:
        body.append('<div class="txt">这个项目没有资产提示词。</div>')
    body.append("</section>")

    # 视频提示词：每一段一份，放在最后
    body.append('<section class="part" id="video"><h2>视频提示词</h2>')
    body.append('<div class="hint">提示词里的 @图N 是<strong>每一段自己的上传顺序</strong>，每段从图1开始，'
                "不是全片统一编号。生成某一段时，按该段的「本段上传顺序」依次上传参考图，再粘贴这一段的提示词。</div>")
    for i, seg in enumerate(segs):
        n = i + 1
        body.append('<article class="card segment" id="vp-%d">' % n)
        body.append('<div class="seg-head"><span class="seg-title">%s提示词 · %s</span>'
                    '<span class="seg-meta">%s · %s</span></div>'
                    % (seg_name(n), esc(seg["title"]), esc(shot_range(seg)), esc(fmt_seconds(seg_duration(seg)))))
        up = upload_text(seg, assets)
        if up:
            body.append('<div class="hint"><strong>本段上传顺序</strong>（对应提示词里的 @图N）：%s</div>' % esc(up))
        body.append(copy_block("p-v%d" % n, "%s提示词" % seg_name(n), compose_video_prompt(seg, assets)))
        body.append("</article>")
    body.append("</section>")

    return meta, "\n".join(nav), "\n".join(body)


def render_html(data):
    meta, nav, body = build_html(data)
    tpl = TEMPLATE_PATH.read_text(encoding="utf-8")
    for marker in ("<!--@TITLE-->", "<!--@META-->", "<!--@NAV-->", "<!--@BODY-->"):
        if marker not in tpl:
            raise RuntimeError("模板缺少占位符 %s：%s" % (marker, TEMPLATE_PATH))
    return (tpl.replace("<!--@TITLE-->", esc(data["project"]) + " · 导演手册")
               .replace("<!--@META-->", meta)
               .replace("<!--@NAV-->", nav)
               .replace("<!--@BODY-->", body))


# ---------------------------------------------------------------- Markdown


def render_md(data):
    assets = assets_by_id(data)
    segs = data["segments"]
    out = ["# %s · 导演手册" % data["project"], "",
           "体裁：%s ｜ 画幅：%s ｜ 模型：%s ｜ 导演手册 skill %s · 生成于 %s"
           % (data["genre"], data["ratio"], data["model"], skill_version(), date.today().isoformat()), "",
           "## 剧本", ""]
    for sec in normalize_script(data["script"]):
        out += ["### " + sec["title"], "", sec["body"].strip(), ""]
    out += ["## 分镜", "", "### 片段划分", "",
            "| 段落 | 场景 | 镜头 | 总时长 | 需要的参考图 |", "|---|---|---|---|---|"]
    for i, seg in enumerate(segs):
        out.append("| %s | %s | %s | %s | %s |"
                   % (seg_name(i + 1), seg["title"], shot_range(seg), fmt_seconds(seg_duration(seg)),
                      needs_text(seg, assets)))
    out.append("")
    for i, seg in enumerate(segs):
        out += ["### %s · %s" % (seg_name(i + 1), seg["title"]), "",
                "| " + " | ".join(SHOT_TABLE_HEAD) + " |", "|" + "---|" * len(SHOT_TABLE_HEAD)]
        for sh in seg["shots"]:
            out.append("| " + " | ".join(c.replace("|", "｜") for c in shot_cells(sh)) + " |")
        out.append("")
        for sh in seg["shots"]:
            out += ["**%s**" % sh["title"].strip(), "", sh["body"].strip(), ""]
        out += layout_md(seg, assets, "segments[%d]" % i)
    out += ["## 资产提示词", ""]
    if data["assets"]:
        out += ["### 资产编号表", "", "| 编号 | 名称 | 类型 | 图 | 用于 |", "|---|---|---|---|---|"]
        for a in data["assets"]:
            out.append("| %s | %s | %s | %s | %s |" % (
                a["id"], a["name"], a["kind"], asset_images_text(a), used_in_text(data, a["id"])))
        out.append("")
        for a in data["assets"]:
            out += ["### %s · %s（%s，用于%s）" % (a["id"], a["name"], a["kind"], used_in_text(data, a["id"])), ""]
            for pr in a["prompts"]:
                if a["kind"] == "参考帧":
                    out += ["**%s**（不是提示词，不用生成）：%s" % (pr["label"], pr["text"].strip()), ""]
                else:
                    out += ["**%s**" % pr["label"], "", "```", pr["text"].strip(), "```", ""]
    else:
        out += ["这个项目没有资产提示词。", ""]
    out += ["## 视频提示词", "",
            "提示词里的 @图N 是每一段自己的上传顺序，每段从图1开始，不是全片统一编号。", ""]
    for i, seg in enumerate(segs):
        out += ["### %s提示词 · %s（%s，%s）" % (seg_name(i + 1), seg["title"], shot_range(seg),
                                              fmt_seconds(seg_duration(seg))), ""]
        up = upload_text(seg, assets)
        if up:
            out += ["本段上传顺序（对应提示词里的 @图N）：" + up, ""]
        out += ["```", compose_video_prompt(seg, assets), "```", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- 入口


def safe_filename(name):
    return re.sub(r"[\\/:*?\"<>|&'#%$`\s]+", "_", name).strip("_") or "项目"


def layout_main(data, args):
    """只有调度数据时：校验格式，画调度图，列出核对结果。"""
    rep = Report()
    segs = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segs, list) or not segs:
        rep.error("segments", "缺少，或不是非空列表")
    else:
        for i, seg in enumerate(segs):
            p = "segments[%d]" % i
            if not isinstance(seg, dict) or not ("blocking" in seg or "readback" in seg):
                rep.error(p, "每段要有 blocking 或 readback")
                continue
            for key in ("blocking", "readback"):
                if key in seg:
                    check_layout_schema(seg[key], "%s.%s" % (p, key), rep)
    if rep.errors:
        print("调度数据有 %d 处错误，没有生成文件：" % len(rep.errors), file=sys.stderr)
        for e in rep.errors:
            print("  - " + e, file=sys.stderr)
        return 1
    found = 0
    body = ['<section class="part" id="layout"><h2>调度图</h2>']
    for i, seg in enumerate(segs):
        f = readback_findings(seg, {}, "segments[%d]" % i)
        found += len(f)
        for path, msg in f:
            print("核对  %s：%s" % (path, msg), file=sys.stderr)
        body.append("<h3>%s</h3>" % esc(seg.get("title") or seg_name(i + 1)))
        body.append(layout_html(seg, {}, "segments[%d]" % i))
    body.append("</section>")
    if args.check:
        print("格式没问题；核对发现 %d 处要处理" % found)
        return 0
    project = data.get("project") or "项目"
    tpl = TEMPLATE_PATH.read_text(encoding="utf-8")
    meta = ('<span class="project">%s</span><span class="tag">调度图（分镜阶段）</span>'
            '<span class="tag">导演手册 skill %s · 生成于 %s</span>' % (esc(project), esc(skill_version()), date.today().isoformat()))
    out = (tpl.replace("<!--@TITLE-->", esc(project) + " · 调度图").replace("<!--@META-->", meta)
              .replace("<!--@NAV-->", '<a class="top-item" href="#layout">调度图</a>').replace("<!--@BODY-->", "\n".join(body)))
    out_path = Path(args.output) if args.output else Path("%s_调度图.html" % safe_filename(project))
    out_path.write_text(out, encoding="utf-8")
    print("已生成：%s（核对发现 %d 处要处理；只检查文字和坐标，不代表出片一定对）" % (out_path.resolve(), found))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 handbook.json 生成为导演手册 HTML（或 Markdown）。")
    ap.add_argument("input", help="handbook.json 的路径")
    ap.add_argument("-o", "--output", help="输出路径；默认是当前目录下的 项目名_导演手册.html")
    ap.add_argument("--md", action="store_true", help="生成同结构的 Markdown，不生成 HTML")
    ap.add_argument("--check", action="store_true", help="只校验，不生成文件")
    ap.add_argument("--layout", action="store_true",
                    help="输入只有调度数据（{\"project\":…, \"segments\":[{\"title\":…, \"blocking\":…, \"readback\":…}]}），"
                         "只画调度图并核对，用在交付分镜时（见 references/readback.md）")
    ap.add_argument("--max-seconds", type=float, help="单个段落的时长上限（用户平台的数字）；默认按模型名取 2.0→15、2.5→30")
    ap.add_argument("--max-images", type=int, help="单个段落的参考图上限（用户平台的数字）；默认按模型名取 2.0→9、2.5→30")
    args = ap.parse_args(argv)

    try:
        raw = Path(args.input).read_text(encoding="utf-8-sig")
    except OSError as e:
        print("读不到输入文件：%s" % e, file=sys.stderr)
        return 2
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print("handbook.json 不是合法的 JSON：第 %d 行第 %d 列，%s" % (e.lineno, e.colno, e.msg), file=sys.stderr)
        print("常见原因：字符串里的换行要写成 \\n，英文双引号要写成 \\\"，最后一项后面不能有逗号。", file=sys.stderr)
        return 2

    if args.layout:
        return layout_main(data, args)

    rep = Report()
    validate(data, args.max_seconds, args.max_images, rep)
    for w in rep.warnings:
        print("警告  " + w, file=sys.stderr)
    if rep.errors:
        print("handbook.json 有 %d 处错误，没有生成文件：" % len(rep.errors), file=sys.stderr)
        for e in rep.errors:
            print("  - " + e, file=sys.stderr)
        print("请按 references/handbook-html.md 的字段说明补齐后重新运行。", file=sys.stderr)
        return 1

    if args.check:
        print("结构校验通过（%d 个警告）。只检查了字段、格式和几项常见写法；站位、道具朝向、取景、关键动作能不能看懂，要人工核对。"
              % len(rep.warnings))
        return 0

    ext = ".md" if args.md else ".html"
    out_path = Path(args.output) if args.output else Path("%s_导演手册%s" % (safe_filename(data["project"]), ext))
    content = render_md(data) if args.md else render_html(data)
    out_path.write_text(content, encoding="utf-8")
    print("已生成：%s（结构校验通过，%d 个警告；画面调度要人工核对）" % (out_path.resolve(), len(rep.warnings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
