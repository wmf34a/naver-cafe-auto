#!/usr/bin/env python3
"""네이버 카페 글쓰기 - 공식 Open API 클라이언트.

표준 라이브러리만 사용한다. 설치할 것 없음.

  python3 naver_cafe.py auth                     최초 1회. refresh token 발급
  python3 naver_cafe.py post draft.md --cafe 육진대 --board 공지
  python3 naver_cafe.py post draft.md --cafe 육진대 --board 공지 --dry-run

API 문서: https://developers.naver.com/docs/login/cafe-api/cafe-api.md
"""
import argparse
import http.server
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAFES = os.path.join(HERE, "cafes.json")
TOKENS = os.path.expanduser("~/.naver-cafe/token.json")
REDIRECT = "http://localhost:8080/callback"
API = "https://openapi.naver.com/v1/cafe/{clubid}/menu/{menuid}/articles"


def die(msg):
    print(f"오류: {msg}", file=sys.stderr)
    sys.exit(1)


def creds():
    cid, secret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        die("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다. SKILL.md의 준비 항목 참고.")
    return cid, secret


# ---------- 인증 ----------

def auth():
    """브라우저로 동의받고 refresh token을 저장한다. 최초 1회만."""
    cid, secret = creds()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in got
            self.wfile.write(
                ("<h2>%s</h2><p>터미널로 돌아가라.</p>" % ("연결됐다." if ok else "실패했다."))
                .encode("utf-8")
            )

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", 8080), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://nid.naver.com/oauth2.0/authorize?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "state": state}
    )
    print("브라우저에서 네이버 로그인 후 동의하면 된다.\n안 열리면 아래 주소를 직접 열어라:\n" + url + "\n")
    webbrowser.open(url)

    for _ in range(180):
        if got:
            break
        time.sleep(1)
    srv.server_close()

    if "code" not in got:
        die(f"인증 코드를 못 받았다. 응답: {got or '없음(3분 초과)'}")
    if got.get("state") != state:
        die("state 불일치. 다시 시도해라.")

    tok = _token_call({
        "grant_type": "authorization_code", "client_id": cid, "client_secret": secret,
        "code": got["code"], "state": state,
    })
    if "refresh_token" not in tok:
        die(f"토큰 발급 실패: {tok}")
    _save(tok)
    print(f"저장했다 → {TOKENS}")


def _token_call(params):
    req = urllib.request.Request(
        "https://nid.naver.com/oauth2.0/token?" + urllib.parse.urlencode(params)
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _save(tok):
    os.makedirs(os.path.dirname(TOKENS), exist_ok=True)
    prev = _load()
    prev.update(tok)
    prev["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 300
    fd = os.open(TOKENS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(prev, f)


def _load():
    try:
        with open(TOKENS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def access_token():
    tok = _load()
    if not tok.get("refresh_token"):
        die("인증 안 됐다. 먼저 `python3 naver_cafe.py auth` 를 돌려라.")
    if tok.get("access_token") and time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    cid, secret = creds()
    new = _token_call({
        "grant_type": "refresh_token", "client_id": cid,
        "client_secret": secret, "refresh_token": tok["refresh_token"],
    })
    if "access_token" not in new:
        die(f"토큰 갱신 실패: {new}. refresh token이 만료됐으면 `auth` 를 다시 돌려라.")
    _save(new)
    return new["access_token"]


# ---------- 마크다운 → 카페 HTML ----------

def md_to_html(md):
    """마크다운을 카페가 받는 HTML로 바꾸고, 이미지 경로는 따로 뽑아낸다.

    2026-09-09 실측: <b> <i> <a> <blockquote> <hr> <br> 전부 통과하고 서식도 살아난다.
    한때 태그가 막힌다고 판단했는데 오진이었다 — 진짜 원인은 <a href="..."> 의
    쌍따옴표(403)와 연속 등록 제한이었다. 그래서 href 는 홑따옴표로 쓴다.

    첨부 이미지는 네이버가 글 끝에 붙인다 — 본문 중간 위치는 지정할 수 없다.
    """
    images = []

    def grab(m):
        """URL 이면 본문에 <img> 로 박고, 로컬 경로면 첨부로 뺀다.

        첨부는 본문 맨 끝에 몰리고 발행 후 에디터로 열면 깨진다. 원하는 자리에
        넣으려면 upload_images.py 로 R2 에 올려 URL 을 쓴다. src 도 홑따옴표다.
        """
        src = m.group(1).strip()
        if src.startswith(("http://", "https://")):
            return f"<img src='{src}'>"
        images.append(src)
        return ""

    md = re.sub(r"!\[[^\]]*\]\(([^)]+)\)", grab, md)

    def inline(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", s)
        # href 는 반드시 홑따옴표 — 쌍따옴표면 카페가 글 전체를 거절한다
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<a href='\2'>\1</a>", s)
        return re.sub(r"^\s*[-*]\s+", "· ", s)

    out, quote = [], []

    def flush_quote():
        # 인용구 안에서는 <br> 이 글자 그대로 보이고 개행문자는 무시된다.
        # 줄마다 <blockquote> 를 따로 여는 게 유일하게 줄바꿈이 사는 방법이다.
        if quote:
            out.append("".join(f"<blockquote>{q}</blockquote>" for q in quote))
            quote.clear()

    for line in md.split("\n"):
        s = line.rstrip()
        if s.startswith(">"):
            quote.append(inline(s.lstrip("> ").rstrip()))
            continue
        flush_quote()
        if re.fullmatch(r"-{3,}", s):
            out.append("<hr>")
            continue
        h = re.match(r"^#{1,6}\s+(.*)", s)
        out.append(f"<b>{inline(h.group(1))}</b>" if h else inline(s))
    flush_quote()

    # blockquote / hr 는 블록 요소라 앞뒤에 <br> 를 또 넣으면 빈 줄이 벌어진다
    html = "<br>\n".join(out)
    html = re.sub(r"<br>\n(?=<(?:blockquote|hr)\b)", "\n", html)
    html = re.sub(r"(</blockquote>|<hr>)<br>\n", r"\1\n", html)
    return html.strip(), images


def escape_quotes(s):
    """쌍따옴표를 엔티티로 바꾼다.

    2026-09-09 실측: 본문이나 제목에 생 " 가 들어가면 403 코드 999로 거절당한다.
    &quot; 로 바꾸면 통과한다. ' & < > 는 그대로 통과하므로 건드리지 않는다.
    md_to_html 이 만드는 태그는 href 까지 홑따옴표라 이 치환에 걸리지 않는다.
    """
    return s.replace('"', "&quot;")


def split_draft(text):
    """첫 번째 '# 제목' 줄을 제목으로, 나머지를 본문으로 쓴다."""
    lines = text.lstrip().split("\n")
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).strip()
    return None, text.strip()


# ---------- 요청 ----------

def enc(s, double):
    """전송 방식에 따라 인코딩이 다르다. 둘 다 실측으로 확인했다.

    2026-09-09, 같은 문자열을 여러 방식으로 올려 카페에서 눈으로 확인한 결과:

      텍스트만 (form-urlencoded) -> 이중 (UTF-8 인코딩 후 MS949로 재인코딩)
      이미지 첨부 (multipart)    -> 단일 (UTF-8 퍼센트 인코딩)

    반대로 하면 양쪽 다 한글이 깨진다. 문서의 Java 예제도 form 쪽은 이중,
    multipart 쪽은 단일로 서로 다르게 쓰고 있다 — 오타가 아니라 실제 규칙이다.

    HTTP 200은 접수됐다는 뜻일 뿐 한글이 멀쩡하다는 뜻이 아니다 — 인코딩을
    바꿨으면 응답 코드가 아니라 카페에 올라간 글자를 봐야 한다.
    """
    once = urllib.parse.quote(s, safe="", encoding="utf-8")
    return urllib.parse.quote(once, safe="", encoding="cp949") if double else once


def multipart(fields, images):
    boundary = "----naverCafe" + secrets.token_hex(8)
    buf = bytearray()
    for k, v in fields.items():
        buf += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode("utf-8")
    for path in images:
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            blob = f.read()
        buf += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
                f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
        buf += blob + b"\r\n"
    buf += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def post(args):
    cafes = json.load(open(CAFES, encoding="utf-8")) if os.path.exists(CAFES) else {}
    cafe = cafes.get(args.cafe)
    if not cafe:
        die(f"'{args.cafe}' 카페가 {CAFES} 에 없다. 등록된 카페: {list(cafes) or '없음'}")
    menuid = cafe.get("boards", {}).get(args.board)
    if menuid is None:
        die(f"'{args.board}' 게시판이 없다. 등록된 게시판: {list(cafe.get('boards', {})) or '없음'}")

    raw = open(args.draft, encoding="utf-8").read()
    title, body = split_draft(raw)
    title = args.title or title
    if not title:
        die("제목이 없다. 초안 첫 줄을 '# 제목' 으로 쓰거나 --title 을 넘겨라.")
    html, images = md_to_html(body)
    images = [os.path.join(os.path.dirname(os.path.abspath(args.draft)), i)
              if not os.path.isabs(i) else i for i in images] + (args.image or [])
    missing = [i for i in images if not os.path.exists(i)]
    if missing:
        die(f"이미지 파일이 없다: {missing}")

    opts = {
        "openyn": "true" if args.public else "false",
        "searchopen": "true" if args.public else "false",
        "replyyn": "true", "scrapyn": "true",
    }
    url = API.format(clubid=cafe["clubid"], menuid=menuid)

    if args.dry_run:
        print(f"[dry-run] {url}\n제목: {title}\n이미지: {images or '없음'}\n공개: {opts['openyn']}\n"
              f"--- 본문 HTML ---\n{html}")
        return

    # 이미지가 붙으면 multipart 로 나가므로 단일, 아니면 이중이다.
    double = (args.encode != "single") if args.encode else not images
    fields = {"subject": enc(escape_quotes(title), double),
              "content": enc(escape_quotes(html), double), **opts}
    if images:
        data, ctype = multipart(fields, images)
    else:
        data = urllib.parse.urlencode(fields, safe="%").encode("ascii")
        ctype = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + access_token(), "Content-Type": ctype,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        die(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")

    msg = res.get("message", {})
    result = msg.get("result", res)
    if msg.get("status") not in (None, "200") and str(result.get("status", "")) != "200":
        die(f"발행 실패: {res}")
    print("발행했다 → " + str(result.get("articleUrl") or res))


def main():
    p = argparse.ArgumentParser(description="네이버 카페 글쓰기")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="최초 1회 OAuth 인증")
    w = sub.add_parser("post", help="초안 파일을 카페에 발행")
    w.add_argument("draft", help="마크다운 초안 경로")
    w.add_argument("--cafe", required=True)
    w.add_argument("--board", required=True)
    w.add_argument("--title", help="초안 첫 줄 대신 쓸 제목")
    w.add_argument("--image", action="append", help="추가 첨부 이미지 (반복 가능)")
    w.add_argument("--public", action="store_true", help="전체 공개 + 검색 허용")
    w.add_argument("--encode", choices=["single", "double"], help="글자 깨질 때만 건드려라")
    w.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    auth() if a.cmd == "auth" else post(a)


if __name__ == "__main__":
    main()
