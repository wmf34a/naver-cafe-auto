#!/usr/bin/env python3
"""사진을 R2에 올리고, 초안에 넣을 마크다운 이미지 줄을 뽑아준다.

카페 API 첨부는 본문 맨 끝에 몰리고, 발행 후 에디터로 열면 깨진다.
대신 R2에 올려 <img> 로 본문에 직접 박으면 위치도 자유롭고 수정에도 안전하다.

  python3 upload_images.py drafts/photos_grouped 2026-05-불암산

내용이 같은 파일은 다시 올리지 않는다 (키에 내용 해시가 들어간다).
"""
import argparse
import glob
import hashlib
import os
import re
import subprocess
import sys
import urllib.parse

BUCKET = os.environ.get("CAFE_R2_BUCKET", "cafe-images")
PUBLIC = os.environ.get("CAFE_R2_PUBLIC_URL",
                        "https://pub-4e79e68377314ca0a8634dfb0dcee058.r2.dev")

# wrangler 는 Cloudflare 계정을 찾아야 한다. 계정이 연결된 프로젝트 안에서
# 돌리거나, CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID 환경변수를 준다.
# 이 경로가 없는 컴퓨터(운영진 노트북 등)에서는 현재 디렉터리에서 돌린다.
_CWD = "/Users/mailplug/revision/yukjindae-map"
WRANGLER_CWD = _CWD if os.path.isdir(_CWD) else os.getcwd()


def key_for(path, prefix):
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
    stem = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", stem).strip("-") or "photo"
    ext = os.path.splitext(path)[1].lower() or ".jpg"
    return f"{prefix}/{slug}-{digest}{ext}"


def upload(path, key):
    r = subprocess.run(
        ["npx", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
         "--file", path, "--remote"],
        cwd=WRANGLER_CWD, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-800:] or r.stderr[-800:], file=sys.stderr)
        sys.exit(
            f"업로드 실패: {path}\n"
            "Cloudflare 인증이 없으면 CLOUDFLARE_API_TOKEN 과 CLOUDFLARE_ACCOUNT_ID 를 "
            "환경변수로 넣어라. R2 없이 가려면 upload_images.py 를 건너뛰고 "
            "naver_cafe.py 의 --image 로 첨부하면 된다 (사진이 본문 맨 끝에 붙는다).")


def main():
    p = argparse.ArgumentParser(description="카페 글용 이미지를 R2에 올린다")
    p.add_argument("directory", help="사진이 있는 디렉터리")
    p.add_argument("prefix", help="R2 키 접두어 (예: 2026-05-불암산)")
    a = p.parse_args()

    files = sorted(glob.glob(os.path.join(a.directory, "*.jpg"))
                   + glob.glob(os.path.join(a.directory, "*.png")))
    if not files:
        sys.exit(f"이미지가 없다: {a.directory}")

    print(f"{len(files)}장 업로드 중...\n", file=sys.stderr)
    lines = []
    for f in files:
        key = key_for(f, a.prefix)
        upload(f, key)
        # 키에 한글이 있어도 카페로 나가는 URL 은 ASCII 여야 안전하다
        url = f"{PUBLIC}/{urllib.parse.quote(key)}"
        print(f"  올림  {os.path.basename(f)}", file=sys.stderr)
        lines.append(f"![]({url})")

    print("\n초안에 붙여 넣을 줄 — 원하는 문단 사이에 두면 그 자리에 나온다:\n")
    print("\n\n".join(lines))


if __name__ == "__main__":
    main()
