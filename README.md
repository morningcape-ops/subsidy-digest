# 補助金ダイジェスト

Jグランツ公開API → Claude(Haiku)で要約 → 静的サイト生成 → GitHub Pagesへ毎朝自動公開。

## 公開手順(初回のみ・約15分)
1. GitHubで新しい **public** リポジトリを作り、このフォルダの中身をpushする。
2. Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` を登録する。
3. Settings → Pages → Source を **GitHub Actions** にする。
4. Actions タブ → `daily-build` → Run workflow で初回実行。以後は毎朝6時(JST)に自動更新。
5. 公開URLをGoogle Search Consoleに登録し、`/sitemap.xml` を送信する。

## ローカルで試す
```bash
MAX_NEW=5 python scripts/build.py   # APIキーなしでも動く(要約は簡易版)
```
注意: APIキーなしで作った`data/items.json`は簡易要約のままキャッシュされる。本番前に削除すること。

## 収益化(アクセスが付いてから)
`config.json` の `ad_snippet` に広告/アフィリエイトのHTMLを貼ると、各詳細ページに表示される。
`analytics_snippet` にはアクセス解析タグを入れる。

## コストの目安
Haiku要約は1件あたり約0.1〜0.3円。1日30件でも月100〜300円未満。
