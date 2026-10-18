#!/usr/bin/env python3
"""把 handbook.json 生成为一个离线的导演手册 HTML（或同结构的 Markdown）。

用法：
    python3 build_handbook.py handbook.json                 # 生成 项目名_导演手册.html
    python3 build_handbook.py handbook.json -o out.html     # 指定输出路径
    python3 build_handbook.py handbook.json --md            # 生成同结构的 Markdown
    python3 build_handbook.py handbook.json --check         # 只校验，不生成

只用 Python 标准库，兼容 Python 3.8 及以上。字段说明见 references/handbook-html.md。
版式固定：剧本 → 分镜 → 资产提示词 → 视频提示词（第一段、第二段……放在最后），每次生成都一样。
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "handbook-template.html"

SHOT_TITLE_RE = re.compile(
    r"^镜头\s*(\d+)｜(内景|外景)｜(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*秒｜(.+)$"
)
NEGATIVE_LEAD = "以下内容一律不要出现"

DEFAULT_MAX_SECONDS = {"2.5": 30, "2.0": 15}
DEFAULT_MAX_IMAGES = {"2.5": 30, "2.0": 9}

# 人物图的名称：这两个叫法在【参考素材绑定】里都只写人物名，不加括号
CHARACTER_SHEET_LABELS = ("人物四视图", "四格图")

# 场景图在【参考素材绑定】里的叫法（「四视图」是旧名，当作「场景多机位」处理）
SCENE_ROLE = {"母版": "主图", "场景多机位": "多机位", "四视图": "多机位", "走位图": "人物走位"}

# 表情项的粗略检查：近景、中景、特写的镜头正文里，至少要出现脸部的字眼（只写「平静」「克制」不算）
FACE_WORDS = re.compile(r"[眼眉嘴唇喉颌脸额鼻泪颊腮牙瞳睫眶]|下巴")
WIDE_SIZES = ("大远景", "远景", "全景")

# 视频提示词全篇用中文全角标点
HALF_WIDTH = re.compile(r'[,;:?!()"]')

# 资产阶段的内部术语：视频模型看不懂，不能出现在视频提示词里
INTERNAL_TERMS = ("主机位", "母版", "场景多机位", "四视图", "走位图")

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
                    need_text(pr, "text", pp, rep)
                    if lab is not None:
                        labels.append(lab)
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
        need_text(seg, "sound", p, rep)
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
        if neg is not None and NEGATIVE_LEAD not in neg:
            rep.warn(p + ".negative", "没有以「以下内容一律不要出现」开头")
        if "cinematography" in seg and not is_text(seg["cinematography"]):
            rep.error(p + ".cinematography", "不需要这个块就删掉字段，写了就不能为空")

        if "refs" in seg:
            rep.warn(p + ".refs", "refs 已不再手写：【参考素材绑定】由脚本按本段的 assets 生成；已忽略")
        extra = seg.get("refs_extra", [])
        if not isinstance(extra, list) or not all(is_text(r) for r in extra):
            rep.error(p + ".refs_extra", "写了就必须是非空文字的列表，用来补充参考视频、参考音频之类的行")

        items = seg.get("assets", [])
        n_images = 0
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
                    continue
                if aid in seen:
                    rep.warn(ip, "资产「%s」在本段重复列出" % aid)
                seen.add(aid)
                used_ids.add(aid)
                labels = asset_labels[aid]
                if use is None:
                    n_images += len(labels)
                elif (not isinstance(use, list) or not use or not all(isinstance(u, str) for u in use)):
                    rep.error(ip + ".use", "必须是非空的提示词名称列表，如 [\"母版\", \"场景多机位\"]")
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
        body_chars = 0
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
                body_chars += len(re.sub(r"\s+", "", body_txt))
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
            if (body_txt is not None and m.group(5).strip() not in WIDE_SIZES
                    and not FACE_WORDS.search(body_txt)):
                rep.warn(sp + ".body",
                         "镜头%d 的正文没有写到脸部的可见变化（眼、眉、嘴、喉、下巴……）；只写「平静」「克制」之类的词不算。"
                         "镜头里没有人脸时可以忽略（见 video-prompt.md 第 3 项）" % no)
            if (is_text(lines_txt) and lines_txt.strip() != "无" and body_txt is not None
                    and "（" not in body_txt):
                rep.warn(sp + ".body",
                         "镜头%d 有台词，但没有按「角色（语气）……说：“台词”」写出语气（括号里不超过 3 个词，不能省）" % no)
            if is_text(lines_txt) and body_txt is not None:
                claimed = [int(n) for n in re.findall(r"(\d+)\s*字", lines_txt)]
                quotes = re.findall(r"[“\"](.*?)[”\"]", body_txt)
                if claimed and quotes:
                    actual = sum(len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", q)) for q in quotes)
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
            if prev_end is not None and abs(start - prev_end) > 1e-6:
                rep.warn(sp + ".title", "起始秒数 %g 和上一个镜头的结束 %g 不连续" % (start, prev_end))
            if end <= start:
                rep.warn(sp + ".title", "结束时间必须晚于起始时间")
            prev_end = end
        if prev_end is not None and sec_limit is not None and prev_end > sec_limit:
            rep.warn(p + ".shots",
                     "总时长约 %g 秒，超过所选版本的默认上限 %d 秒（用户的平台数字不同时可忽略）" % (prev_end, sec_limit))
        if prev_end is not None and prev_end > 0 and body_chars / prev_end < 35:
            rep.warn(p + ".shots",
                     "镜头正文平均只有 %.0f 字/秒（共 %d 字、%g 秒），偏短（参考约 35–50 字/秒）。逐个镜头检查有没有写出：人物的位置和走位、"
                     "表情的可见变化、手和道具的动作、环境里在动的东西（见 video-prompt.md「每个镜头写到什么程度」）；"
                     "镜头确实很简单时可以忽略" % (body_chars / prev_end, body_chars, prev_end))

    for aid in asset_labels:
        if aid not in used_ids:
            rep.warn("assets", "资产「%s」没有被任何段落使用" % aid)


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
        for p in a["prompts"]:
            if use is None or p["label"] in use:
                (people if a["kind"] == "人物" else others).append((a, p))
    return [(i + 1, a, p) for i, (a, p) in enumerate(people + others)]


def seg_refs(seg, assets):
    """【参考素材绑定】的各行：角色一行，场景一行（主图、多机位、人物走位），其他类型各一行。"""
    upload = seg_upload(seg, assets)
    lines = []
    chars = [(n, a, p) for n, a, p in upload if a["kind"] == "人物"]
    if chars:
        lines.append("角色：" + "，".join(
            "%s%s@图%d" % (a["name"], "" if p["label"] in CHARACTER_SHEET_LABELS else "（%s）" % p["label"], n)
            for n, a, p in chars))
    kinds = []
    for n, a, p in upload:
        if a["kind"] != "人物" and a["kind"] not in kinds:
            kinds.append(a["kind"])
    for kind in kinds:
        group = [(n, a, p) for n, a, p in upload if a["kind"] == kind]
        owners = []
        for n, a, p in group:
            if a not in owners:
                owners.append(a)
        parts = []
        for a in owners:
            if kind == "场景":
                txt = "，".join("%s@图%d" % (SCENE_ROLE.get(p["label"], p["label"]), n)
                               for n, a2, p in group if a2 is a)
                parts.append(txt if len(owners) == 1 else "%s %s" % (a["name"], txt))
            else:
                parts.append("，".join("%s（%s）@图%d" % (a["name"], p["label"], n)
                                      for n, a2, p in group if a2 is a))
        lines.append("%s：%s" % (kind, "；".join(parts)))
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
            % (esc(data["project"]), esc(data["genre"]), esc(data["ratio"]), esc(data["model"])))

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
           "体裁：%s ｜ 画幅：%s ｜ 模型：%s" % (data["genre"], data["ratio"], data["model"]), "",
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 handbook.json 生成为导演手册 HTML（或 Markdown）。")
    ap.add_argument("input", help="handbook.json 的路径")
    ap.add_argument("-o", "--output", help="输出路径；默认是当前目录下的 项目名_导演手册.html")
    ap.add_argument("--md", action="store_true", help="生成同结构的 Markdown，不生成 HTML")
    ap.add_argument("--check", action="store_true", help="只校验，不生成文件")
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
        print("校验通过（%d 个警告）" % len(rep.warnings))
        return 0

    ext = ".md" if args.md else ".html"
    out_path = Path(args.output) if args.output else Path("%s_导演手册%s" % (safe_filename(data["project"]), ext))
    content = render_md(data) if args.md else render_html(data)
    out_path.write_text(content, encoding="utf-8")
    print("已生成：%s" % out_path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
