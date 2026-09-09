# cafe-post

네이버 카페에 글을 쓰고, 고치고, 발행하는 Claude Code 스킬.

공식 [Cafe Open API](https://developers.naver.com/docs/login/cafe-api/cafe-api.md)를 쓰므로
브라우저 자동화나 로그인 세션이 필요 없다. 표준 라이브러리만 쓰고 설치할 패키지가 없다.

초안은 파일로 남는다. 대화로 몇 번이든 고친 뒤, 명시적으로 승인했을 때만 올라간다.

## 설치

스킬 디렉터리로 바로 클론한다.

```bash
git clone https://github.com/wmf34a/naver-cafe-auto.git .claude/skills/cafe-post
```

Claude Code를 그 상위 디렉터리에서 실행하면 스킬이 잡힌다.

## 설정 (최초 1회)

### 1. 네이버 애플리케이션

[개발자센터](https://developers.naver.com/apps/#/register)에서 등록한다.

- 사용 API에 **카페** 선택 — API 권한관리 탭에서 체크됐는지 반드시 확인 (안 하면 403)
- 환경: **PC웹**
- 서비스 URL `http://localhost:8080`
- Callback URL `http://localhost:8080/callback` — 한 글자도 틀리면 인증이 막힌다

검수 신청은 하지 않는다. 검수 없이도 앱 등록자 계정으로는 정상 동작한다.

### 2. 열쇠를 환경변수로

```bash
echo '\nexport NAVER_CLIENT_ID="..."\nexport NAVER_CLIENT_SECRET="..."' >> ~/.zshenv
source ~/.zshenv
```

`.zshrc`가 아니라 `.zshenv`에 넣는다. 비대화형 셸도 읽어야 스크립트가 값을 본다.

### 3. 인증

```bash
python3 .claude/skills/cafe-post/scripts/naver_cafe.py auth
```

브라우저에서 동의하면 refresh token이 `~/.naver-cafe/token.json`(0600)에 저장된다.
이후로는 자동 갱신되므로 다시 할 일이 없다. 컴퓨터마다 한 번씩 필요하다.

로그인하는 계정은 대상 카페에 **글쓰기 권한이 있는 등급으로 가입**돼 있어야 한다.

### 4. 카페 등록

`cafes.json`에 대상을 적는다.

```json
{ "육진대": { "clubid": "31732268", "boards": { "정규행사": 16 } } }
```

카페에서 게시판을 열면 주소가 `cafe.naver.com/f-e/cafes/{clubid}/menus/{menuid}` 형태다.
두 숫자를 그대로 옮기면 된다.

### 5. 이미지 호스팅 (선택)

사진을 본문 중간에 넣으려면 R2가 필요하다. 없으면 `--image`로 첨부할 수 있지만
본문 맨 끝에 몰리고, 발행 후 에디터로 열면 깨진다.

```bash
export CAFE_R2_BUCKET="cafe-images"
export CAFE_R2_PUBLIC_URL="https://pub-....r2.dev"
```

`wrangler`가 Cloudflare 계정을 찾아야 한다. 계정이 연결된 프로젝트 안에서 돌리거나
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`를 환경변수로 준다.

## 쓰는 법

Claude에게 말로 시킨다.

```
육진대 카페에 6월 행사 후기 써줘. 사진은 ~/Downloads/6월행사.zip
둘째 문단 줄여줘
올려줘
```

직접 돌릴 수도 있다.

```bash
S=.claude/skills/cafe-post/scripts

python3 $S/upload_images.py <사진폴더> <접두어>      # 사진 → R2, 마크다운 줄 출력
python3 $S/naver_cafe.py post 초안.md --cafe 육진대 --board 정규행사 --dry-run
python3 $S/naver_cafe.py post 초안.md --cafe 육진대 --board 정규행사
```

`--public`을 붙이면 전체 공개 + 검색 허용이 된다. 기본은 멤버 공개다.

## 알아둘 제약

문서와 실제가 다른 지점이 여럿이다. 아래는 전부 실측으로 확인한 값이다.

| 항목 | 실제 |
| --- | --- |
| 연속 등록 | 약 **2분 간격** 필요. 더 빠르면 403 |
| 인코딩 (텍스트만) | 이중 — UTF-8 인코딩 후 MS949로 재인코딩 |
| 인코딩 (이미지 첨부) | 단일 — UTF-8 퍼센트 인코딩 |
| `"` 쌍따옴표 | 거절 → `&quot;`로 치환 (스크립트가 자동 처리) |
| `<a href>` | **홑따옴표 필수**. 쌍따옴표면 글 전체가 403 |
| 인용구 줄바꿈 | 안에서 `<br>`은 글자로 보인다. 줄마다 `<blockquote>`를 따로 연다 |
| 첨부 이미지 | 본문 맨 끝에 몰린다. 문단 사이 배치는 `<img>`로만 가능 |
| 글쓰기 한도 | 200건/일, 네이버 계정당 |

실패는 전부 `403` + 코드 `999`로 똑같이 뜬다. 원인을 알려주지 않으므로
**막히면 먼저 2분 기다렸다 재시도**한다. 대부분 연속 등록 제한이다.

그리고 **HTTP 200을 성공으로 믿지 마라.** 200은 접수됐다는 뜻이고, 한글이 깨진
채로도 200이 온다. 인코딩 관련해 뭔가 바꿨으면 카페에 올라간 글자를 눈으로 봐야 한다.

## 자체 검증

```bash
cd .claude/skills/cafe-post/scripts && python3 test_naver_cafe.py
```

파싱·인코딩·multipart 조립을 네트워크 없이 확인한다. 스크립트를 고쳤으면 이걸 돌린다.

## 파일

```
SKILL.md                    Claude가 읽는 작업 지침
README.md                   사람이 읽는 설치·설정 문서
cafes.json                  카페/게시판 번호
scripts/naver_cafe.py       OAuth 인증 + 발행
scripts/upload_images.py    R2 업로드 + 마크다운 줄 생성
scripts/test_naver_cafe.py  자체 검증
```

비밀값은 저장소에 들어가지 않는다. Client ID/Secret은 환경변수에, refresh token은
`~/.naver-cafe/`에 있다.
