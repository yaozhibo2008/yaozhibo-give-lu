#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""story.md -> story-data.js

数据层生成器：把 story.md 解析成 window.STORY_DATA = { SCENES, ENDINGS }。
index.html 只负责渲染，不再内联任何剧情字面量。

用法:
    python build_story_data.py            # 生成 story-data.js
    python build_story_data.py --check    # 只校验，不写文件

数值换算复用 balance_check.to_delta，保证「脚本验证的分布」与「游戏内跑出的数值」
出自同一份公式，不存在第二套近似实现。
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from balance_check import to_delta  # noqa: E402

SRC = os.path.join(HERE, 'story.md')
OUT = os.path.join(HERE, 'story-data.js')
END_KEYS = ['tian', 'nuan', 'yihan', 'shuli']


def strip_quote(s):
    """剥掉 story.md 外层包裹的一对「」，内部对话的「」保留。"""
    s = s.strip()
    if s.startswith('「'):
        s = s[1:]
    if s.endswith('」'):
        s = s[:-1]
    return s.strip()


def parse_opening(txt):
    opening = []
    if '## opening' not in txt:
        raise SystemExit('story.md 缺少 ## opening 段')
    block = txt.split('## opening', 1)[1].split('---', 1)[0]
    for line in block.splitlines():
        line = line.strip()
        if line.startswith('- 「'):
            opening.append(strip_quote(line[2:]))
    if not opening:
        raise SystemExit('opening 段解析为空')
    return opening


def parse_chapters(txt):
    chapters = []
    for blk in re.split(r'\n### 第', txt)[1:]:
        head = blk.split('\n', 1)[0].strip()
        if not head or head[0] not in '一二三四五六七八九十':
            continue
        body = blk.split('```yaml', 1)[1].split('```', 1)[0]
        msgs, opts, cur, mode = [], [], None, None
        for raw in body.splitlines():
            st = raw.strip()
            if st == 'messages:':
                mode = 'msg'
                continue
            if st == 'options:':
                mode = 'opt'
                continue
            if not st:
                continue
            if mode == 'msg' and st.startswith('- '):
                msgs.append(strip_quote(st[2:]))
            elif mode == 'opt':
                if st.startswith('- text:'):
                    cur = {'text': strip_quote(st[len('- text:'):]), 'delta': None, 'replies': []}
                    opts.append(cur)
                elif st.startswith('delta:') and cur is not None:
                    cur['delta'] = st[len('delta:'):].strip()
                elif st.startswith('- ') and cur is not None and cur['delta']:
                    cur['replies'].append(strip_quote(st[2:]))
        if len(opts) != 3:
            raise SystemExit('章节「第%s」选项数 %d != 3' % (head, len(opts)))
        chapters.append({'title': '第' + head, 'messages': msgs, 'options': opts})
    if len(chapters) != 10:
        raise SystemExit('章节数 %d != 10' % len(chapters))
    return chapters


def parse_endings(txt):
    if '## endings' not in txt:
        raise SystemExit('story.md 缺少 ## endings 段')
    blocks = re.split(r'\n### 结局', txt.split('## endings', 1)[1])[1:]
    endings = []
    for blk in blocks:
        head = blk.split('\n', 1)[0].strip()          # 例：1【双向偏爱·甜结局】
        cond, body, in_body = '', [], False
        for raw in blk.splitlines()[1:]:
            st = raw.strip()
            if st.startswith('- **触发条件**'):
                cond = st.split('：', 1)[1].strip()
            elif st.startswith('- **正文**'):
                in_body = True
            elif in_body and (st == '---' or st.startswith('## ')):
                break
            elif in_body and st and not st.startswith('- **') and not st.startswith('#'):
                body.append(st)
        endings.append({
            'title': head[1:].strip().strip('【】').replace('·', ' · '),
            'cond': cond,
            'body': body,
        })
    if len(endings) != 4:
        raise SystemExit('结局数 %d != 4' % len(endings))
    return endings


def build():
    txt = open(SRC, encoding='utf-8').read()
    opening = parse_opening(txt)
    chapters = parse_chapters(txt)
    endings = parse_endings(txt)

    scenes = {}
    for idx, ch in enumerate(chapters):
        sid = 's%d' % (idx + 1)
        msgs = (opening + ch['messages']) if idx == 0 else ch['messages']
        choices = []
        for o in ch['options']:
            m = re.match(r'分享欲([+-]\d+)｜在意值([+-]\d+)｜耐心值([+-]\d+)', o['delta'] or '')
            if not m:
                raise SystemExit('%s 存在无法解析的 delta：%r' % (ch['title'], o['delta']))
            ds, dc, dp = to_delta((int(m.group(1)), int(m.group(2)), int(m.group(3))))
            if not (2 <= len(o['replies']) <= 4):
                raise SystemExit('%s 选项 replies 条数 %d 越界' % (ch['title'], len(o['replies'])))
            choices.append({
                'text': o['text'],
                'ds': ds, 'dc': dc, 'dp': dp,
                'replies': [{'who': '', 'text': r} for r in o['replies']],
            })
        scenes[sid] = {
            'title': ch['title'],
            'next': ('s%d' % (idx + 2)) if idx < 9 else None,
            'messages': [{'who': '', 'text': s} for s in msgs],
            'choices': choices,
        }

    data = {'SCENES': scenes, 'ENDINGS': dict(zip(END_KEYS, endings))}
    return data, opening, chapters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验，不写文件')
    args = ap.parse_args()

    data, opening, chapters = build()

    if not args.check:
        payload = (
            '/* 自动生成，请勿手改。\n'
            '   源文件: story.md   生成脚本: build_story_data.py\n'
            '   数值: 由 balance_check.to_delta 换算（构建期完成，运行期只做加法） */\n'
            'window.STORY_DATA = '
            + json.dumps(data, ensure_ascii=False, indent=1)
            + ';\n'
        )
        with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
            f.write(payload)

    msg_total = sum(len(s['messages']) for s in data['SCENES'].values())
    rep_total = sum(len(c['replies']) for s in data['SCENES'].values() for c in s['choices'])
    cho_total = sum(len(s['choices']) for s in data['SCENES'].values())
    print('章节 %d | 选项 %d | messages %d | replies %d | 结局 %d'
          % (len(data['SCENES']), cho_total, msg_total, rep_total, len(data['ENDINGS'])))
    print('s1 messages %d（含开场 %d）' % (len(data['SCENES']['s1']['messages']), len(opening)))
    print('每章消息数', [len(s['messages']) for s in data['SCENES'].values()])
    print('结局', [e['title'] for e in data['ENDINGS'].values()])
    if not args.check:
        print('已写出', OUT, '%.1f KB' % (os.path.getsize(OUT) / 1024.0))


if __name__ == '__main__':
    main()
