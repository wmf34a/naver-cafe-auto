#!/usr/bin/env python3
"""python3 test_naver_cafe.py — 네트워크 없이 도는 자체 검증."""
import re
import urllib.parse

from naver_cafe import enc, escape_quotes, md_to_html, multipart, split_draft


def test_split_draft():
    assert split_draft("# 제목이다\n\n본문") == ("제목이다", "본문")
    assert split_draft("제목 없음\n둘째줄") == (None, "제목 없음\n둘째줄")


def test_md_to_html():
    html, imgs = md_to_html(
        "## 소제목\n**굵게** 그리고 *기울임*\n- 항목\n[링크](https://a.b)\n![](사진.jpg)"
    )
    assert "<b>소제목</b>" in html
    assert "<b>굵게</b>" in html and "<i>기울임</i>" in html
    assert "· 항목" in html
    assert "<a href='https://a.b'>링크</a>" in html
    assert imgs == ["사진.jpg"], imgs
    assert "![" not in html  # 이미지 문법은 본문에서 빠져야 한다


def test_url_image_goes_inline_local_stays_attachment():
    """URL 이미지는 본문 제자리에, 로컬 경로는 첨부로 갈라져야 한다."""
    html, imgs = md_to_html("위<br>![](https://x.dev/a.jpg)<br>아래\n![](사진.jpg)")
    assert "<img src='https://x.dev/a.jpg'>" in html, html
    assert imgs == ["사진.jpg"], imgs
    assert escape_quotes(html) == html, "생성한 img 태그가 엔티티 치환에 걸리면 안 된다"


def test_href_uses_single_quotes():
    """href 에 쌍따옴표가 들어가면 카페가 글 전체를 403으로 거절한다."""
    html, _ = md_to_html("[링크](https://a.b)")
    assert '"' not in html, html
    assert escape_quotes(html) == html, "생성한 태그가 엔티티 치환에 걸리면 안 된다"


def test_blockquote_and_hr():
    html, _ = md_to_html("> 첫 줄\n> 둘째 줄\n\n---\n본문")
    assert "<blockquote>첫 줄</blockquote><blockquote>둘째 줄</blockquote>" in html, html
    assert "<br>" not in html.split("<hr>")[0], "인용구 안 <br> 은 글자로 보인다"
    assert "<hr>" in html
    assert "<br>\n<blockquote>" not in html, "블록 요소 앞 <br> 는 빠져야 한다"

def test_escape_quotes():
    """생 쌍따옴표는 403을 부른다. 나머지 특수문자는 건드리지 않는다."""
    assert escape_quotes('가격 "삼만원"') == "가격 &quot;삼만원&quot;"
    assert escape_quotes("A & B < C > D 'e'") == "A & B < C > D 'e'"


def test_encoding_roundtrip():
    """문서 규칙: UTF-8 인코딩 후 MS949로 재인코딩. 서버가 두 번 풀면 원문이 나와야 한다."""
    s = "카페 글 <b>테스트</b>"
    once = enc(s, double=False)
    assert urllib.parse.unquote(once, encoding="utf-8") == s

    twice = enc(s, double=True)
    assert "%25" in twice, "이중 인코딩이면 %가 %25로 escape 돼야 한다"
    assert urllib.parse.unquote(
        urllib.parse.unquote(twice, encoding="cp949"), encoding="utf-8"
    ) == s


def test_encoded_body_survives_urlencode():
    """미리 인코딩한 값을 urlencode가 다시 escape하면 안 된다 (safe='%')."""
    body = urllib.parse.urlencode({"subject": enc("한글", True)}, safe="%")
    assert "%2525" not in body, "삼중 인코딩됐다 — safe='%' 가 빠졌다"


def test_multipart_has_field_and_file(tmp="/tmp/_cafe_test.jpg"):
    open(tmp, "wb").write(b"\xff\xd8\xff-fake-jpeg")
    data, ctype = multipart({"subject": "제목"}, [tmp])
    assert ctype.startswith("multipart/form-data; boundary=")
    assert b'name="subject"' in data
    assert b'name="image"; filename="_cafe_test.jpg"' in data
    assert b"fake-jpeg" in data
    assert data.rstrip().endswith(b"--")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("전부 통과")
