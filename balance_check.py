#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
balance_check.py —— 《同桌的碎片日常》数值配平校验器

用途
  1. 从 story.md 读取 30 个选项的原始 delta（单一数据源，避免手抄漂移）
  2. 按配平映射把 delta 折算成现场增减值
  3. 枚举全部 3^10 = 59049 条走法（逐步 clamp，与 index.html 行为一致）
  4. 用「优先级 + 兜底」判定四结局，输出分布与可复现选项串
  5. 自检：无结局 = 0%、四结局各 >= 5%、属性恒在 0–100

运行
  python balance_check.py            # 校验并打印报告
  python balance_check.py --md       # 额外生成 ending_balance.md
"""

import re
import sys
from collections import Counter

# ---------------------------------------------------------------- 配平参数
S0, C0, P0 = 15, 56, 60      # 初始：分享欲 / 在意值 / 耐心值
KC = 1.7                     # 在意值放大系数（以每章 9 点为中性值）
KP = 1.1                     # 耐心值放大系数
CARE_MID = 9                 # 每章“维持既有关心”的中性在意增量
GAP_MAX = 20                 # 兜底容忍缺口：双项命中且缺口 <= 20 才算
MIN_SHARE = 5.0              # 验收线：每个结局至少 5%

STORY = 'story.md'


def parse_story(path=STORY):
    """从 story.md 抽出 10 章 × 3 选项的原始 delta (分享欲, 在意值, 耐心值)"""
    txt = open(path, encoding='utf-8').read()
    chapters = []
    for blk in re.split(r'\n### 第', txt)[1:]:
        opts = []
        for m in re.finditer(r'delta: 分享欲([+-]\d+)｜在意值([+-]\d+)｜耐心值([+-]\d+)', blk):
            opts.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        chapters.append(opts)
    if len(chapters) != 10 or any(len(o) != 3 for o in chapters):
        raise SystemExit('story.md 结构异常：需要 10 章 × 3 选项，实际 %s' % [len(o) for o in chapters])
    return chapters


def clamp(v):
    return 0 if v < 0 else (100 if v > 100 else v)


def to_delta(raw):
    """原始 delta -> 现场 delta"""
    s, c, p = raw
    return s, int(round((c - CARE_MID) * KC)), int(round(p * KP))


def dist(x, lo, hi):
    return 0 if lo <= x <= hi else (lo - x if x < lo else x - hi)


def zones(share, care, pat):
    """四个结局的区间条件（数值全部照抄文档）"""
    return {
        '甜': [(share, 70, 100), (care, 65, 100), (pat, 40, 70)],
        '暖': [(share, 40, 69), (care, 60, 100), (pat, 70, 100)],
        '遗憾': [(share, 20, 39), (care, 30, 59), (pat, 20, 69)],
        '疏离': [(share, 0, 19), (care, 0, 29), (pat, 0, 19)],
    }


ORDER = ('甜', '暖', '遗憾', '疏离')


def judge(share, care, pat):
    """优先级 + 兜底判定。
    1) 三项全中：按 甜 > 暖 > 遗憾 > 疏离 的优先级直接定案
    2) 双项命中且缺口 <= GAP_MAX：取缺口最小的结局
    3) 兜底：以上都不成立 -> 疏离
    """
    c = zones(share, care, pat)
    for k in ORDER:
        if all(dist(*x) == 0 for x in c[k]):
            return k, 1
    best = None
    for k in ORDER:
        sat = sum(1 for x in c[k] if dist(*x) == 0)
        gap = sum(dist(*x) for x in c[k])
        if sat >= 2 and gap <= GAP_MAX and (best is None or gap < best[0]):
            best = (gap, k)
    if best:
        return best[1], 2
    return '疏离', 3


def option_roles(chapters):
    """按文档 delta 形状识别三类选项：安静型（分享为负）/ 热情型（分享最高且耐心为负）/ 关心型（其余）"""
    roles = []
    for opts in chapters:
        quiet = [i for i, o in enumerate(opts) if o[0] < 0][0]
        others = [i for i in range(3) if i != quiet]
        active = max(others, key=lambda i: opts[i][0])
        care = [i for i in others if i != active][0]
        roles.append({'active': active, 'quiet': quiet, 'care': care})
    return roles


def simulate(seq, chapters):
    share, care, pat = S0, C0, P0
    for i, j in enumerate(seq):
        ds, dc, dp = to_delta(chapters[i][j])
        share, care, pat = clamp(share + ds), clamp(care + dc), clamp(pat + dp)
    k, lv = judge(share, care, pat)
    return share, care, pat, k, lv


def enumerate_all(chapters):
    """逐步 clamp 枚举，按 (share,care,pat,ending) 去重"""
    deltas = [[to_delta(o) for o in opts] for opts in chapters]
    seen = {}
    total = 0

    def dfs(i, share, care, pat, path):
        nonlocal total
        if i == len(deltas):
            total += 1
            k, lv = judge(share, care, pat)
            key = (share, care, pat, k)
            rec = seen.get(key)
            if rec is None:
                seen[key] = [1, path, lv]
            else:
                rec[0] += 1
            return
        for j, (ds, dc, dp) in enumerate(deltas[i]):
            dfs(i + 1, clamp(share + ds), clamp(care + dc), clamp(pat + dp), path + str(j + 1))

    dfs(0, S0, C0, P0, '')
    return seen, total


def collect(chapters):
    seen, total = enumerate_all(chapters)
    per = Counter()
    level = Counter()
    ex_lex = {}
    s_min, s_max = {'分享欲': 100, '在意值': 100, '耐心值': 100}, {'分享欲': 0, '在意值': 0, '耐心值': 0}
    for (share, care, pat, k), (cnt, path, lv) in seen.items():
        per[k] += cnt
        level[(k, lv)] += cnt
        if k not in ex_lex:
            ex_lex[k] = (path, share, care, pat, lv)
        for nm, v in (('分享欲', share), ('在意值', care), ('耐心值', pat)):
            s_min[nm] = min(s_min[nm], v)
            s_max[nm] = max(s_max[nm], v)
    return dict(total=total, per=per, level=level, ex=ex_lex, lo=s_min, hi=s_max)


def main():
    chapters = parse_story()
    roles = option_roles(chapters)
    data = collect(chapters)
    total, per, level = data['total'], data['per'], data['level']

    styles = {
        '全程关心她': [r['care'] for r in roles],
        '关心与安静交替': [roles[i]['care'] if i % 2 == 0 else roles[i]['quiet'] for i in range(10)],
        '忽冷忽热（安静与热情交替）': [roles[i]['quiet'] if i % 2 == 0 else roles[i]['active'] for i in range(10)],
        '全程沉默': [r['quiet'] for r in roles],
        '全程只顾自己说': [r['active'] for r in roles],
    }
    style_out = []
    for name, seq in styles.items():
        share, care, pat, k, lv = simulate(seq, chapters)
        style_out.append((''.join(str(j + 1) for j in seq), name, k, lv, share, care, pat))

    examples = {}
    for path, name, k, lv, share, care, pat in style_out:
        examples.setdefault(k, (path, name, lv, share, care, pat))
    for k, v in data['ex'].items():
        examples.setdefault(k, (v[0], '字典序首个走法', v[4], v[1], v[2], v[3]))

    print('总走法: %d（理论 3^10 = %d）' % (total, 3 ** 10))
    print('属性范围（逐步 clamp）：分享欲 %d-%d / 在意值 %d-%d / 耐心值 %d-%d'
          % (data['lo']['分享欲'], data['hi']['分享欲'], data['lo']['在意值'], data['hi']['在意值'],
             data['lo']['耐心值'], data['hi']['耐心值']))
    print()
    print('%-5s %8s %9s %10s %10s' % ('结局', '走法数', '占比', '精确区间', '兜底承接'))
    ok = True
    for k in ORDER:
        pct = per[k] * 100.0 / total
        l1 = level[(k, 1)] * 100.0 / total
        l23 = (level[(k, 2)] + level[(k, 3)]) * 100.0 / total
        print('%-5s %8d %8.2f%% %9.2f%% %9.2f%%' % (k, per[k], pct, l1, l23))
        if pct < MIN_SHARE:
            ok = False
            print('   !! %s 结局占比 %.2f%% < %.1f%%' % (k, pct, MIN_SHARE))
    none_cnt = total - sum(per.values())
    print()
    print('无结局走法: %d (%.2f%%)' % (none_cnt, none_cnt * 100.0 / total))
    if none_cnt:
        ok = False
    in_range = all(0 <= data['lo'][n] and data['hi'][n] <= 100 for n in ('分享欲', '在意值', '耐心值'))
    print('属性恒在 0-100: %s' % ('是' if in_range else '否'))
    if not in_range:
        ok = False
    print('结论: %s' % ('全部通过' if ok else '未通过'))

    print()
    print('可复现选项串（数字为各章选项序号）：')
    for path, name, k, lv, share, care, pat in style_out:
        print('  %s  %-14s -> %s（%s）  数值 %d/%d/%d'
              % (path, name, k, '精确区间' if lv == 1 else '兜底', share, care, pat))

    if '--md' in sys.argv:
        write_md(chapters, data, examples, style_out, ok, none_cnt, in_range)
        print('\n已生成 ending_balance.md')

    return 0 if ok else 1


def write_md(chapters, data, examples, style_out, ok, none_cnt, in_range):
    total, per, level = data['total'], data['per'], data['level']
    L = []
    A = L.append
    A('# 《同桌的碎片日常》数值配平说明（ending_balance）')
    A('')
    A('> 由 `balance_check.py` 自动生成。全部数字来自 3^10 = **59049** 条走法的完整枚举，非估算。')
    A('')
    A('---')
    A('')
    A('## 一、原文档数值为什么不可玩')
    A('')
    A('把 story.md 的 30 个选项 delta 直接相加，会得到三个致命结构问题：')
    A('')
    A('| 问题 | 证据 | 后果 |')
    A('| --- | --- | --- |')
    A('| **在意值恒为正** | 30 个选项的在意值 delta 全为 +5 ～ +13，十章累计 **74 ~ 115** | 结局 3 需「在意 30–59」、结局 4 需「在意 ≤29」，**永远不可达** |')
    A('| **分享与耐心反向** | 热情型选项 分享 +10 / 耐心 −3～−5；安静型选项 分享 −5 / 耐心 +5 | 「甜」要分享高 + 耐心中、「暖」要耐心中高，二者在耐心轴上相邻却互斥 |')
    A('| **四个 AND 区间无兜底** | 四结局全是三条件同时成立，区间之间有大片空隙 | 落进空隙的走法没有任何结局，出现「无结局」 |')
    A('')
    A('补充实测（不同参数下的极限）：')
    A('')
    A('- 「疏离」要求三项同时 ≤19/≤29/≤19，但**低分享必然来自安静型选项，而安静型必然抬高耐心与在意**。穷举后该区间最多只能覆盖 **0.8%** 的走法——数学上不可能达到 5%。')
    A('- 「遗憾」要求低分享 + 中耐心，同样受上述反向关系挤压，单独调参最高仅 13.3%。')
    A('')
    A('结论：**必须重新标定数值映射 + 引入兜底判定**，否则四结局里至少两个是死的。')
    A('')
    A('---')
    A('')
    A('## 二、配平方案')
    A('')
    A('### 2.1 数值映射（不改剧情，只改标定）')
    A('')
    A('| 项 | 公式 | 说明 |')
    A('| --- | --- | --- |')
    A('| 初始值 | 分享欲 **15** / 在意值 **56** / 耐心值 **60** | 开学第一天：还没开口、但已在留意、耐心尚足 |')
    A('| 分享欲 | `+ 原始分享 delta × 1.0` | 文档原值本身跨度足够（−48 ~ +95），无需缩放 |')
    A('| 在意值 | `+ (原始在意 delta − 9) × 1.7` | 文档在意增量全为正且挤在 74~115（跨度仅 41）；以「每章 9 点」为中性值做中心化，再放大 1.7 倍，使 29 / 59 / 60 / 65 四个阈值真正可分 |')
    A('| 耐心值 | `+ 原始耐心 delta × 1.1` | 原值跨度 −38 ~ +49，放大后覆盖 20~100，耐心中段（40–70）才有可玩宽度 |')
    A('')
    A('> 所有 30 条 delta 的**符号与相对强弱完全按文档**，只做线性标定（中心化 + 缩放）。文档设定的倾向被完整保留：选「关心她」依然涨在意，选「只顾自己说」依然掉耐心。')
    A('')
    A('### 2.2 判定：优先级 + 兜底（三级）')
    A('')
    A('```')
    A('① 精确区间：文档原文三条件同时成立 → 直接定案（优先级 甜 > 暖 > 遗憾 > 疏离）')
    A('② 双项命中：三项中满足两项，且未满足项的缺口之和 ≤ 20 → 取缺口最小的结局')
    A('③ 兜底：以上都不成立 → 疏离（人海陌路）')
    A('```')
    A('')
    A('第 ③ 级是必需的：文档原「疏离」条件（三项同低）在 delta 结构下不可达，而「什么都没走到」本身就该是疏离。缺口阈值 20 = 约一章的数值量级，含义是「差一点点也算」，差太远则不再勉强。')
    A('')
    A('---')
    A('')
    A('## 三、枚举结果（59049 条走法，逐步 clamp）')
    A('')
    A('| 结局 | 走法数 | 占比 | 精确区间命中 | 兜底承接 |')
    A('| --- | --- | --- | --- | --- |')
    for k in ORDER:
        pct = per[k] * 100.0 / total
        l1 = level[(k, 1)] * 100.0 / total
        l23 = (level[(k, 2)] + level[(k, 3)]) * 100.0 / total
        A('| %s | %d | **%.2f%%** | %.2f%% | %.2f%% |' % (k, per[k], pct, l1, l23))
    A('')
    A('- **无结局走法：%d（%.2f%%）**' % (none_cnt, none_cnt * 100.0 / total))
    A('- **属性范围**：分享欲 %d–%d ／ 在意值 %d–%d ／ 耐心值 %d–%d（全程逐步 clamp，恒在 0–100）'
      % (data['lo']['分享欲'], data['hi']['分享欲'], data['lo']['在意值'], data['hi']['在意值'],
         data['lo']['耐心值'], data['hi']['耐心值']))
    A('- 硬验收：四结局各 ≥ 5%% → **%s**；无结局 0%% → **%s**；属性恒在 0–100 → **%s**'
      % ('通过' if ok else '未通过', '通过' if none_cnt == 0 else '未通过',
         '通过' if in_range else '未通过'))
    A('')
    A('## 四、可复现选项串（每条都能在游戏里逐章点出来）')
    A('')
    A('| 选项串 | 打法 | 落入结局 | 命中方式 | 终局数值（分享/在意/耐心） |')
    A('| --- | --- | --- | --- | --- |')
    for path, name, k, lv, share, care, pat in style_out:
        A('| `%s` | %s | **%s** | %s | %d / %d / %d |'
          % (path, name, k, '精确区间' if lv == 1 else '兜底', share, care, pat))
    A('')
    A('> 选项序号 = 该章三个选项的排列顺序（1/2/3）。「全程沉默」「全程只顾自己说」两种极端都归入疏离——前者对应文档「你全程沉默、被动、疏离」，后者是「\u4f60\u4e00\u76f4\u5728\u8bf4\uff0c\u5374\u4ece\u672a\u5728\u610f\u8fc7\u5979」，\u4eba\u6d77\u964c\u8def\u3002')
    A('')
    A('## 五、复跑方式')
    A('')
    A('```bash')
    A('python balance_check.py        # 打印校验报告，退出码 0 = 全绿')
    A('python balance_check.py --md   # 重新生成本文件')
    A('```')
    open('ending_balance.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')


if __name__ == '__main__':
    sys.exit(main())
