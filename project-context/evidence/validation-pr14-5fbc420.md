# PR #14 application-core validation at `5fbc420`

Verified on 2026-10-17.

- Pull request: <https://github.com/SoloMidMiram/CatsChannel/pull/14>
- Head commit: `5fbc42092e4946d0e2afaf80bde8e25ca5b31d4d`
- Base commit: `5192e443b7e51ff09042b636ecebe6119738a96d`
- GitHub state: open and mergeable
- GitHub CI: Ubuntu Python 3.11/3.13 and Windows Python 3.11/3.13 passed
- WSL Python 3.11 baseline: 163 passed, 1 skipped
- WSL Python 3.11 with userbot extra: 163 passed, 1 skipped
- WSL Python 3.13 with userbot extra: 163 passed, 1 skipped
- Windows Python 3.11: 162 passed, 2 skipped
- Ruff lint/format, offline lock consistency, offline sdist/wheel builds, wheel
  contents, CLI import/config smoke, and whitespace checks passed

The offline pilot uses the real aiogram dispatcher and a mocked Bot API transport.
No live Telegram or YouTube call was made. A live private-channel pilot remains a
separate task and was intentionally excluded from this pull request.
