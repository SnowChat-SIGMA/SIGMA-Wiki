"""
pages/*.md 의 머리 4줄(제목·메타·키워드·요약)을 읽어 index.md 를 만든다.

사용법 (레포 루트에서):
    python tools/build_index.py            # index.md 생성
    python tools/build_index.py --check    # 형식만 검사 (CI 용, 파일 안 씀)
    python tools/build_index.py --today 2026-11-25   # 기준일 지정

페이지 머리 형식 (pages/ 의 모든 파일이 지켜야 함):
    # [절차|행사|규정|안내] 제목
    분야: ... | 대상: ... | 상태: ... | 유효기간: YYYY-MM-DD ~ YYYY-MM-DD | 갱신: YYYY-MM-DD
    키워드: 단어, 단어, ...
    요약: 한 문장

나중에 sigma-pipeline 의 render.py 가 같은 형식으로 페이지를 찍으면
이 스크립트(또는 같은 로직)로 index.md 를 자동 갱신하면 된다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "pages"
INDEX = ROOT / "index.md"

REQUIRED_META = ["분야", "대상", "유효기간", "갱신"]
DATE_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")


@dataclass
class Page:
    path: str
    kind: str
    title: str
    meta: dict[str, str]
    keywords: list[str]
    summary: str
    valid_from: dt.date
    valid_to: dt.date


class PageFormatError(Exception):
    pass


def parse_page(file: Path) -> Page:
    lines = [l.rstrip("\n") for l in file.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 4:
        raise PageFormatError("머리 4줄(제목·메타·키워드·요약)이 없음")

    m = re.match(r"^#\s*\[(.+?)\]\s*(.+)$", lines[0])
    if not m:
        raise PageFormatError("1줄: '# [종류] 제목' 형식이 아님")
    kind, title = m.group(1).strip(), m.group(2).strip()

    meta: dict[str, str] = {}
    for part in lines[1].split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            meta[k.strip()] = v.strip()
    missing = [k for k in REQUIRED_META if k not in meta]
    if missing:
        raise PageFormatError(f"2줄: 메타 항목 없음 {missing}")

    r = DATE_RANGE.search(meta["유효기간"])
    if not r:
        raise PageFormatError("2줄: 유효기간이 'YYYY-MM-DD ~ YYYY-MM-DD' 형식이 아님")
    vf, vt = (dt.date.fromisoformat(x) for x in r.groups())
    if vf > vt:
        raise PageFormatError("2줄: 유효기간 시작이 끝보다 늦음")

    if not lines[2].startswith("키워드:"):
        raise PageFormatError("3줄: '키워드:' 로 시작해야 함")
    keywords = [k.strip() for k in lines[2].split(":", 1)[1].split(",") if k.strip()]
    if not keywords:
        raise PageFormatError("3줄: 키워드가 비어 있음")

    if not lines[3].startswith("요약:"):
        raise PageFormatError("4줄: '요약:' 으로 시작해야 함")
    summary = lines[3].split(":", 1)[1].strip()

    return Page(
        path=f"pages/{file.name}",
        kind=kind,
        title=title,
        meta=meta,
        keywords=keywords,
        summary=summary,
        valid_from=vf,
        valid_to=vt,
    )


def render_index(pages: list[Page], today: dt.date) -> str:
    out = [
        "# snowtice 위키 목록",
        f"갱신: {today.isoformat()} | 유효한 페이지: {len(pages)}개",
        "",
        "질문에 맞는 페이지를 고를 때는 '대상'과 '키워드'를 먼저 본다.",
        "학과 페이지와 공통 페이지가 모두 맞으면 학과 페이지를 우선한다.",
        "",
    ]
    by_field: dict[str, list[Page]] = {}
    for p in pages:
        top = p.meta["분야"].split(">")[0].strip()
        by_field.setdefault(top, []).append(p)

    for field in sorted(by_field):
        out.append(f"## {field}")
        for p in sorted(by_field[field], key=lambda x: x.path):
            out += [
                f"- path: {p.path}",
                f"  제목: [{p.kind}] {p.title}",
                f"  대상: {p.meta['대상']}",
                f"  유효기간: {p.valid_from.isoformat()} ~ {p.valid_to.isoformat()}",
                f"  키워드: {', '.join(p.keywords)}",
                f"  요약: {p.summary}",
            ]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="형식 검사만 하고 파일을 쓰지 않음")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (기본: 오늘, KST)")
    args = ap.parse_args()

    kst = dt.timezone(dt.timedelta(hours=9))
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(kst).date()

    files = sorted(PAGES.glob("*.md"))
    if not files:
        print("pages/ 에 md 파일이 없음", file=sys.stderr)
        return 1

    pages, errors, expired = [], [], []
    for f in files:
        try:
            p = parse_page(f)
        except PageFormatError as e:
            errors.append(f"{f.name}: {e}")
            continue
        if p.valid_to < today:
            expired.append(p.path)   # 끝난 페이지: 목록에서 빼고, 삭제 대상으로 알림
        else:
            pages.append(p)

    for e in errors:
        print(f"[형식 오류] {e}", file=sys.stderr)
    for e in expired:
        print(f"[유효기간 지남 → pages/ 에서 삭제 필요] {e}", file=sys.stderr)
    if errors:
        return 1

    if args.check:
        print(f"형식 검사 통과: 유효 {len(pages)}개, 만료 {len(expired)}개")
        return 0

    INDEX.write_text(render_index(pages, today), encoding="utf-8")
    print(f"index.md 생성: 유효 {len(pages)}개, 만료 {len(expired)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())