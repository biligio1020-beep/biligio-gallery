#!/usr/bin/env python3
"""Generate /gallery/ static pages from Pages CMS JSON entries. Python stdlib only."""
from __future__ import annotations
import html
import json
import re
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content' / 'gallery'
MEDIA = ROOT / 'media' / 'gallery'
OUT = ROOT / 'dist' / 'gallery'
CATEGORIES = {
    'performance': '공연·연주회', 'event': '행사·축제',
    'shooting': '촬영·방송', 'school': '학교·기관',
    'experience': '악기 체험·전시',
}
SLUG = re.compile(r'^[a-z0-9][a-z0-9-]*$')

def h(value):
    return html.escape(str(value or ''), quote=True)

def image_url(value):
    """Only allow site-local PagesCMS gallery media; reject unsafe / offsite URLs."""
    if isinstance(value, dict):
        value = value.get('src') or value.get('path') or value.get('url') or ''
    if not isinstance(value, str):
        return ''
    prefix = '/gallery/media/'
    if not value.startswith(prefix):
        return ''
    name = value[len(prefix):]
    if not name or '\\' in name or any(x in ('', '.', '..') for x in name.split('/')):
        return ''
    # Percent-encode each path segment and preserve normal UTF-8 names.
    return prefix + '/'.join(quote(x, safe='-_.~') for x in name.split('/'))

def page(title, description, body, canonical, image=''):
    og_image = f'<meta property="og:image" content="https://biligio.com{h(image)}">' if image else ''
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)} | 빌리지오 BILIGIO</title><meta name="description" content="{h(description)}">
<link rel="canonical" href="https://biligio.com{h(canonical)}">
<meta property="og:title" content="{h(title)}"><meta property="og:description" content="{h(description)}">
{og_image}<link rel="stylesheet" href="/gallery/assets/gallery.css"></head>
<body><header class="site-nav"><nav class="wrap" aria-label="기본 메뉴"><a class="logo" href="/"><img src="/assets/images/brand/biligio-logo.png" alt="빌리지오 홈"></a><div class="navlinks"><a href="/">홈페이지</a><a href="/gallery/">대여 사례</a><a href="/mobile/">모바일 홈</a></div></nav></header>
{body}
<footer class="footer"><div class="wrap">© BILIGIO · 실제 악기 대여 사례를 소개합니다.</div></footer>
<script defer src="/gallery/assets/gallery.js"></script></body></html>'''

def display_date(c):
    mode = c.get('date_display', 'day')
    if mode == 'hidden':
        return ''
    return str(c.get('date', ''))[:7 if mode == 'month' else 10]

def case_meta(c):
    return ' · '.join(h(v) for v in (display_date(c), c.get('instruments')) if v)

def load_cases():
    results = []
    for f in CONTENT.glob('*.json'):
        data = json.loads(f.read_text(encoding='utf-8-sig'))
        if data.get('published') is not True:
            continue
        slug = f.stem
        if not SLUG.fullmatch(slug):
            raise ValueError(f'파일명은 영문/숫자/하이픈만 사용하세요: {f.name}')
        if data.get('url_id') != slug:
            raise ValueError(f'url_id 와 파일명이 달라요: {f.name}, url_id={data.get("url_id")}')
        if not str(data.get('title', '')).strip() or not str(data.get('summary', '')).strip():
            raise ValueError(f'제목과 소개를 입력하세요: {f.name}')
        if data.get('date_display', 'day') not in ('day', 'month', 'hidden'):
            raise ValueError(f'날짜 공개 범위를 확인하세요: {f.name}')
        if data.get('category') not in CATEGORIES:
            raise ValueError(f'카테고리 값을 확인하세요: {f.name}')
        try:
            date.fromisoformat(str(data.get('date', ''))[:10])
        except ValueError as e:
            raise ValueError(f'날짜를 YYYY-MM-DD로 입력하세요: {f.name}') from e
        data['_slug'] = slug
        results.append(data)
    return sorted(results, key=lambda d: (d.get('date') or '', d['_slug']), reverse=True)

def render_list(cases):
    filters = '<button class="filter active" type="button" data-filter="all" aria-pressed="true">전체</button>'
    filters += ''.join(f'<button class="filter" type="button" data-filter="{h(k)}" aria-pressed="false">{h(v)}</button>' for k, v in CATEGORIES.items() if any(c["category"] == k for c in cases))
    cards = []
    for c in cases:
        photo = image_url(c.get('cover')) or next((image_url(p) for p in (c.get('photos') or []) if image_url(p)), '')
        thumb = f'<img src="{h(photo)}" alt="{h(c.get("title"))}" loading="lazy">' if photo else '<span aria-hidden="true">BILIGIO</span>'
        cards.append(f'''<a class="case-card" href="/gallery/{h(c['_slug'])}/" data-category="{h(c['category'])}"><div class="card-image">{thumb}</div>
<div class="card-body"><span class="tag">{h(CATEGORIES[c['category']])}</span><h2>{h(c.get('title'))}</h2>
<p>{h(c.get('summary'))}</p><div class="meta">{case_meta(c)}</div></div></a>''')
    contents = f'<div class="gallery-grid">{"".join(cards)}</div>' if cards else '<div class="empty">게시된 대여 사례가 아직 없습니다.</div>'
    body = f'''<main class="wrap"><section class="hero"><div class="eyebrow">RENTAL STORIES</div><h1>빌리지오 대여 사례</h1>
<p>공연·축제·촬영·학교 현장에서 활용된 악기 대여 사례를 소개합니다.</p></section>
<div class="filters" role="group" aria-label="대여 사례 필터">{filters}</div>{contents}</main>'''
    (OUT / 'index.html').write_text(page('악기 대여 사례', '빌리지오의 공연, 행사, 촬영, 학교 악기 대여 사례 갤러리', body, '/gallery/'), encoding='utf-8')

def render_detail(c):
    cover = image_url(c.get('cover'))
    photos = [image_url(p) for p in (c.get('photos') or [])]
    photos = [x for x in photos if x]
    display = list(dict.fromkeys(([cover] if cover else []) + photos))
    hero = f'<img class="detail-hero" src="{h(display[0])}" alt="{h(c.get("title"))}">' if display else ''
    more = '<div class="detail-photos">' + ''.join(f'<a href="{h(x)}" target="_blank" rel="noopener"><img loading="lazy" src="{h(x)}" alt="{h(c.get("title"))} 현장 사진 {i}"></a>' for i, x in enumerate(display[1:],1)) + '</div>' if len(display)>1 else ''
    date_html = f'<span>대여 진행일: {h(display_date(c))}</span>' if display_date(c) else ''
    body = f'''<main class="wrap detail"><a class="back" href="/gallery/">← 전체 대여 사례로</a>
<div class="eyebrow" style="margin-top:28px">{h(CATEGORIES[c['category']])}</div><h1>{h(c.get('title'))}</h1>
<div class="detail-meta">{date_html}<span>대여 악기: {h(c.get('instruments'))}</span></div>
<p class="lead">{h(c.get('summary'))}</p>{hero}{more}
<section class="cta"><h2>이런 악기가 필요하신가요?</h2><p>사용 목적, 기간, 수량을 알려주시면 대여 방법을 안내합니다.</p><a href="http://qr.kakao.com/talk/.Kl8Ne0UDdGd_YyhfUL4AI0Z02I-" target="_blank" rel="noopener noreferrer">대여 문의하기 →</a></section></main>'''
    slug = c['_slug']
    folder = OUT / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'index.html').write_text(page(c['title'], c.get('summary'), body, f'/gallery/{slug}/', display[0] if display else ''), encoding='utf-8')


def main():
    # Rebuild from scratch: this output subtree is the only directory to deploy.
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / 'assets').mkdir(parents=True)
    shutil.copy2(ROOT / 'assets' / 'gallery.css', OUT / 'assets' / 'gallery.css')
    shutil.copy2(ROOT / 'assets' / 'gallery.js', OUT / 'assets' / 'gallery.js')
    cases = load_cases()
    # Privacy: upload ONLY images referenced by published cases.
    # This controls the website output only; a public GitHub repository remains public.
    photo_values = []
    for case in cases:
        photo_values.append(case.get('cover'))
        photo_values.extend(case.get('photos') or [])
    for value in photo_values:
        url = image_url(value)
        if not url:
            if value:
                raise ValueError(f'잘못된 갤러리 이미지 경로: {value!r}')
            continue
        from urllib.parse import unquote
        relative = unquote(url[len('/gallery/media/'):])
        source = MEDIA / relative
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(MEDIA.resolve()):
            raise ValueError(f'공개 글에서 참조하는 사진이 없습니다: {relative}')
        target = OUT / 'media' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    render_list(cases)
    for case in cases:
        render_detail(case)
    print(f'갤러리 빌드 완료: 공개 글 {len(cases)}개 -> {OUT}')

if __name__ == '__main__':
    main()
