# eq_scratch_bridge

気象庁の地震情報と緊急地震速報(Wolfx)を数字コードに変換して、Scratch / TurboWarp のクラウド変数に送っています。

## 準備

```
py -m pip install -U websocket-client
```

`epicenter_names.txt` を、スクリプトと同じフォルダに置いてください。(重要)

## 設定

自分の値は、環境変数か引数で渡します。

| 内容 | 環境変数 | 引数 |
|---|---|---|
| プロジェクトID | `EQ_PROJECT_ID` | `--project` |
| 連絡先URL(TurboWarp用) | `EQ_CONTACT` | `--contact` |
| ユーザー名(TurboWarp用) | `EQ_USER` | `--user` |

本家Scratchに書くときは、次も設定してください。

```
SCRATCH_USERNAME   = 自分のScratchユーザー名
SCRATCH_SESSION_ID = ブラウザのセッションID
```

パスワードでもログインできるが、失敗しやすいのでセッションIDがおすすめです。

## 使い方

```
py eq_scratch_bridge_v11_public.py                  本番(新しい地震が来たら送る)
py eq_scratch_bridge_v11_public.py --dry            送らず数字だけ表示
py eq_scratch_bridge_v11_public.py --test 数字      テスト数字を送る
py eq_scratch_bridge_v11_public.py --test-wolfx     Wolfxの最新EEWを1件、変換して送る
py eq_scratch_bridge_v11_public.py --once           いちばん新しい地震を1回だけ送って終わる
py eq_scratch_bridge_v11_public.py --server turbowarp --contact 連絡先 --user 名前
```

| 引数 | 内容 |
|---|---|
| `--server` | 送信先。`turbowarp`(初期値) / `scratch` / `both` |
| `--var` | クラウド変数名(初期値 `eqquake`) |
| `--interval` | 通常情報の取得間隔(初期値 15秒) |

## 数字の形式

### 通常情報(28桁)

| 桁 | 内容 |
|---|---|
| 1 | 目印(常に1) |
| 2 | 種類(1=地震情報) |
| 3 | 発表の種類(1=震度速報、2=震源、3=震源・震度、5=遠地、9=その他) |
| 4-11 | 月日時分(MMDDHHMM) |
| 12-13 | 最大震度(10=1、20=2、30=3、40=4、45=5弱、50=5強、55=6弱、60=6強、70=7、00=不明) |
| 14-15 | マグニチュード×10(99=不明) |
| 16-18 | 深さkm(999=不明) |
| 19-22 | 津波の付加文コード(0215=津波の心配なし) |
| 23-26 | 震央地名コード(気象庁のコード、4桁) |
| 27-28 | 情報種別(03=震源・震度情報) |

### 緊急地震速報(18桁)

| 桁 | 内容 |
|---|---|
| 1-2 | 報数 |
| 3-6 | 震央地名コード |
| 7-8 | マグニチュード×10 |
| 9-11 | 深さkm |
| 12-13 | 推定最大震度 |
| 14 | PLUM(isAssumption) |
| 15 | 最終報 |
| 16 | 取消 |
| 17-18 | 種別(01=予報、02=警報) |

## epicenter_names.txt

震央地名コードと地名の対応表。UTF-8。

- 1行目がコード0001、2行目が0002、のように行番号がコードになります。
- 空きは `-` で埋めます。
- `0001 地名` のように、先頭にコードを書く形式でも読めます。

## 取得先

- 気象庁 `https://www.jma.go.jp/bosai/quake/data/`
- Wolfx `wss://ws-api.wolfx.jp/jma_eew` / `https://api.wolfx.jp/jma_eew.json`
- 震央地名のGeoJSON `0Quake/JMA_Region`
