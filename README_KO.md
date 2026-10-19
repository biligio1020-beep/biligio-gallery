# 빌리지오 갤러리 시작 패키지

이 파일들은 **기존 홈페이지 전체를 대체하지 않습니다.** 갤러리 전용 `/gallery/` 폴더만 추가하는 예시 템플릿입니다.
호스팅 설정은 실제 파일질라 경로와 FTPS 지원 여부 확인 후 수정하세요.

## 파일 구성
- `.pages.yml` : Pages CMS 입력 화면 정의(사진 업로드, 제목, 카테고리, 공개 여부)
- `content/gallery/*.json` : 게시글 1개 = JSON 파일 1개 (초안 예시 1개 포함, 공개 안 됨)
- `media/gallery/` : 업로드된 사진의 원본을 GitHub에 저장
- `build_gallery.py` : GitHub의 게시글로 정적 HTML 생성 (Python 표준 라이브러리만 사용)
- `assets/gallery.css` : 갤러리 디자인 CSS
- `assets/gallery.js` : 카테고리 필터
- `.github/workflows/deploy-gallery.yml` : GitHub Actions에서 빌드하고 FTPS로 업로드

## 1. 업로드 전 카페24 체크
1. 파일질라에서 운영 사이트 전체 백업.
2. 오른쪽 서버 원격 경로를 기록. `/www/index.html`의 `/www`가 FTP 로그인 루트 아래 있는지 확인.
3. FileZilla 사이트 관리자에서 **명시적 FTP over TLS (FTPS)** 접속 가능 여부 확인. 단순 FTP가 되는 것만으로 FTPS를 지원한다는 뜻은 아닙니다.
4. 카페24 FTP 국가/IP 차단을 확인. GitHub의 해외 서버 IP가 차단되면 Actions 업로드가 실패합니다.
5. `www/gallery/` 또는 `gallery/`만 대상으로 사용할 별도 폴더 생성. 기존 파일이 없어야 합니다.

## 2. GitHub에 업로드
1. GitHub 로그인 → New repository → 예: `biligio-gallery` → Private 권장 (무료 Actions 한도 확인).
2. 생성한 repository에 이 패키지 파일을 **폴더째가 아니라 내부 파일/폴더**로 업로드.
3. 리포지토리 맨 위에 `.pages.yml` 파일이 보여야 합니다.
4. GitHub Web UI에서는 숨김 파일/숨김 폴더가 ZIP 해제 화면에서 누락될 수 있으므로 반드시 `.pages.yml`과 `.github/workflows/deploy-gallery.yml` 존재를 확인하세요.

## 3. Pages CMS 연결
1. https://app.pagescms.org/ → Sign in with GitHub.
2. Github App 설치 요청 시 방금 만든 `biligio-gallery` repository만 선택해 권한 부여.
3. `biligio-gallery` → `대여 사례` 컬렉션 → 새 글.
4. `url_id`: `event-2026-01` 형태의 영문·숫자·하이픈만 입력하고 이후 바꾸지 않습니다.
5. 사진과 제목, 날짜, 카테고리, 설명 입력. 첫 테스트는 `홈페이지에 공개` OFF.
6. 저장하면 Github `content/gallery/` 또는 `media/gallery/`에 반영됩니다.

## 4. Actions 준비
GitHub repository → Settings → Secrets and variables → Actions → Repository secrets:
- `CAFE24_FTP_HOST`: 예: `host.cafe24.com` (실제 호스트)
- `CAFE24_FTP_USER`: 실제 FTP 아이디
- `CAFE24_FTP_PASSWORD`: 실제 FTP 비밀번호

비밀번호는 GitHub 일반 코드/README/PagesCMS 입력 글에 적지 마세요.

## 5. 자동 배포 초기 테스트
1. `.github/workflows/deploy-gallery.yml`에서 `server-dir: ./www/gallery/`를 실제 파일질라 FTP 로그인 루트 기준으로 수정. FTP 로그인하면 이미 `index.html`이 보이는 상태라면 보통 `./gallery/`입니다.
2. 기본 `dry-run: true`이므로 빌드·FTPS 접속·변경 예정사항을 검토할 수 있지만 **파일 업로드는 하지 않습니다**.
3. Github Actions → Build and deploy BILIGIO gallery → Run workflow → 로그 확인.
4. 결과와 FTP 서버 폴더 위치가 정확하며 기존 파일 삭제 위험이 없는지 다시 확인한 뒤 `dry-run: false` 변경.
5. Pages CMS에서 게시글의 `홈페이지에 공개` ON, 저장 → Actions 성공 후 `https://biligio.com/gallery/` 접속 확인.
6. 이후 자동으로 추가 등록/수정/삭제됩니다 (연결 정상인 경우).

> 호스팅이 FTPS를 제공하지 않으면 첨부된 FTP Deploy Action을 그대로 사용하지 마세요. SFTP 전용 workflow가 필요하거나 다른 배포 경로를 구성해야 합니다. 일반 FTP는 암호화되지 않으므로 권장하지 않습니다.

## 6. PC에서 빌드 확인
Python 3 설치 후 ZIP 압축 해제 폴더에서:
```sh
python3 build_gallery.py
python3 -m http.server 8000 --directory dist
```
브라우저에서 `http://localhost:8000/gallery/` 접속.
공개된 글이 아직 없으면 "게시된 대여 사례가 아직 없습니다."가 정상입니다.

## UTF-8 안내
- `.pages.yml`, JSON 파일, HTML 출력은 UTF-8입니다.
- HTML은 `<meta charset="UTF-8">` 포함.
- URL 식별자는 영문·숫자·하이픈 권장, **보이는 제목과 설명은 한글 가능**.
- 서버의 UTF-8 사용 여부는 FTP 프로토콜, 포트, IP 제한과 별개입니다.

## 운영 전 필수
- 기존 홈페이지 PC/모바일 메뉴에 `/gallery/` 링크 추가(한 번만).
- 대여 업체명·행사명·얼굴·촬영 결과물의 게시 권한 확인.
- 너무 큰 사진은 업로드 전 1600~2000px 권장, WebP/JPEG 압축.
- 공개 글이 삭제되면 배포 과정에서 그 글의 페이지가 삭제될 수 있으므로 PagesCMS에서 수정/비공개만 사용하고 GitHub 이력을 백업으로 활용.
- `www/gallery/` 폴더는 갤러리 전용으로만 쓰고 기존 홈페이지 코드/상품 연동 파일을 넣지 마세요.

## 추가 확인 사항
- 카페24 FTP 서버가 FTPS를 실제로 지원하는가
- GitHub Actions가 실행되는 서버 IP의 카페24 접속 차단 여부
- FileZilla 접속 후 실제 `www` 폴더 위치와 `gallery/` 절대 경로
- 기존 디자인의 헤더, 색상, 상담 URL 등 최종 통합 정보
