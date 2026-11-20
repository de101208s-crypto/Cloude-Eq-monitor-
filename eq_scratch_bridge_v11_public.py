# eq_scratch_bridge_v11_public.py  (公開用)
# 気象庁の地震情報などを数字コードに変換して、Scratch / TurboWarpのクラウド変数に送る
#
# 【注意】
#   ・情報の遅れ・抜け・間違いがありえます。避難などの判断には、必ず公式の情報
#     (気象庁、自治体、テレビ・ラジオなど)を使ってください。
#   ・データの出典(気象庁、Wolfx API、震央地名のGeoJSON)の利用条件は、
#     それぞれの提供元で確認してください。
#   ・本家Scratchのクラウド変数へ、このような外部プログラムから書き込むことが
#     許されるかは、Scratchの決まりを確認してから使ってください。
#
# 準備:
#   py -m pip install -U websocket-client
#
# 自分用に設定するもの(環境変数か引数。コードに直接書かないでね):
#   EQ_PROJECT_ID      = 自分のScratchプロジェクトID  (--project でもOK)
#   EQ_CONTACT         = 自分の連絡先URL。TurboWarpのサーバーに伝わる (--contact でもOK)
#   EQ_USER            = 自分のユーザー名。TurboWarp用 (--user でもOK)
#
# 本家Scratchに書くとき(パスワードやセッションIDは、絶対にコードに書かない・人に見せない):
#   SCRATCH_USERNAME   = 自分のScratchユーザー名
#   (パスワードでのログインは失敗しやすいので、セッションIDを使うのがおすすめ)
#   SCRATCH_SESSION_ID = ブラウザのセッションID
#
# 使い方:
#   py eq_scratch_bridge_v11_public.py --test 11308201140102801002150550   (テスト数字を送る)
#   py eq_scratch_bridge_v11_public.py --once                              (いちばん新しい本物の地震を1回だけ送って終わる)
#   py eq_scratch_bridge_v11_public.py                                     (本番: 新しい地震が来たら送る)
#   py eq_scratch_bridge_v11_public.py --dry                               (送らず数字だけ表示)
#   py eq_scratch_bridge_v11_public.py --server turbowarp --contact 連絡先 --user 名前  (TurboWarpに送る)
#
# 通常情報は旧26桁形式＋末尾種別2桁。EEWは18桁形式:
#   1      目印(常に1)
#   2      種類(1=地震情報)
#   3      発表の種類(1=震度速報、2=震源、3=震源・震度、5=遠地、9=その他)
#   4-11   月日時分(MMDDHHMM)
#   12-13  最大震度(10=1、20=2、30=3、40=4、45=5弱、50=5強、55=6弱、60=6強、70=7、00=不明)
#   14-15  マグニチュード×10(99=不明)
#   16-18  深さkm(999=不明)
#   19-22  津波の付加文コード(気象庁のコード。0215=津波の心配なし)
#   23-26  震央地名コード(気象庁のコード。4桁)
#   27-28  情報種別(01=EEW予報、02=EEW警報、03=震源・震度情報)
# EEW: 報数2｜震央コード4｜M×10 2｜深さ3｜推定最大震度2｜PLUM1｜最終報1｜取消1｜種別2
# EEW種別: 01=予報、02=警報。Wolfx WebSocket/HTTPから取得。PLUM欄はisAssumptionを使用。
import argparse, json, os, queue, re, sys, threading, time, urllib.request, unicodedata
from pathlib import Path

BASE = "https://www.jma.go.jp/bosai/quake/data/"
TW_URL = "wss://clouddata.turbowarp.org/"
WOLFX_EEW_WS = "wss://ws-api.wolfx.jp/jma_eew"
WOLFX_EEW_HTTP = "https://api.wolfx.jp/jma_eew.json"
EPICENTER_GEOJSON_URL = "https://raw.githubusercontent.com/0Quake/JMA_Region/main/%E9%9C%87%E5%A4%AE%E5%9C%B0%E5%90%8D.geojson"
DEFAULT_PROJECT = ""  # 自分のプロジェクトIDを --project か 環境変数 EQ_PROJECT_ID で指定する
EEW_INTERVAL = 2
FINAL_QUIET_SECONDS = 60
HOLD_SECONDS = 120
INT_CODE = {"1": 10, "2": 20, "3": 30, "4": 40,
            "5-": 45, "5+": 50, "6-": 55, "6+": 60, "7": 70}
EEW_INT_CODE = {10: 10, 20: 20, 30: 30, 40: 40,
                45: 45, 46: 45, 50: 50, 55: 55, 60: 60, 70: 70}


# ---------- 取得と変換 ----------
def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "eq-scratch-bridge/5"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def num(v, default=-1):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else default


def issue_code(title):
    if "遠地" in title:
        return 5
    if "震度速報" in title:
        return 1
    if "震源・震度" in title:
        return 3
    if "震源" in title:
        return 2
    return 9


def encode(detail):
    head = detail.get("Head", {})
    body = detail.get("Body", {})
    eq = body.get("Earthquake", {})
    area = eq.get("Hypocenter", {}).get("Area", {})

    t = re.search(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", eq.get("OriginTime", ""))
    mmddhhmm = "".join(t.groups()) if t else "00000000"

    maxint = INT_CODE.get(str(body.get("Intensity", {})
                              .get("Observation", {}).get("MaxInt", "")), 0)

    mag = num(eq.get("Magnitude"))
    mag = 99 if mag < 0 else min(int(round(mag * 10)), 98)

    c = re.search(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+)?/",
                  area.get("Coordinate", ""))
    depth = 999
    if c and c.group(3):
        depth = min(abs(int(c.group(3))) // 1000, 998)

    fc = body.get("Comments", {}).get("ForecastComment", {})
    if isinstance(fc, list):
        fc = fc[0] if fc else {}
    tsunami = str(fc.get("Code", "0")).zfill(4)[-4:]

    epi = str(area.get("Code", "0")).zfill(4)[-4:]

    old_payload = ("1" + "1" + str(issue_code(head.get("Title", "")))
                   + mmddhhmm + f"{maxint:02d}{mag:02d}{depth:03d}" + tsunami + epi)
    return old_payload + "03"


def recent_files(limit):
    items = get_json(BASE + "list.json")
    names = [i.get("json") for i in items if i.get("json")]
    if not names:
        print("list.json の中身の形が想定と違うよ。1件目:", items[:1])
        return []
    return sorted(names, reverse=True)[:limit]


def epicenter_name_codes():
    """同じフォルダの epicenter_names.txt を読む。
    形式A: 1行目=コード0001、2行目=コード0002...
    形式B: 0001 地名 / 0001<TAB>地名 のような明示コード形式。
    """
    path = Path(__file__).with_name("epicenter_names.txt")
    result = {}
    if not path.is_file():
        print("震央地名コード表が見つからないよ。epicenter_names.txt を同じフォルダに置いてね")
        return result

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    explicit_code_count = 0
    populated_count = 0

    for line_no, raw in enumerate(lines, 1):
        value = raw.strip()
        if not value or value == "-":
            continue

        # 先頭に1～4桁のコードが明記されている形式にも対応。
        # 元の正規表現は \\d / \\s が二重エスケープされていたため一致しなかった。
        match = re.match(r"^(\d{1,4})[\s,;，；\t]+(.+)$", value)
        if match:
            code = f"{int(match.group(1)):04d}"
            name = match.group(2).strip()
            explicit_code_count += 1
        else:
            # 1行目を0001として、行番号を気象庁コードとして扱う。
            code = f"{line_no:04d}"
            name = value

        if not name or name == "-":
            continue

        normalized = normalize_epicenter_name(name)
        if not normalized:
            continue
        result[normalized] = code
        populated_count += 1

    print(
        f"震央地名コード表: {path.name} "
        f"({populated_count}地域 / {len(lines)}行、明示コード形式 {explicit_code_count}件)"
    )
    return result

def normalize_epicenter_name(value):
    """震央地名の表記ゆれ（全角英数字・空白等）を正規化する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def load_epicenter_geojson():
    """気象庁震央地名の境界・コード表を取得してローカルキャッシュする。"""
    path = Path(__file__).with_name("epicenter_regions.geojson")
    if not path.exists():
        req = urllib.request.Request(
            EPICENTER_GEOJSON_URL,
            headers={"User-Agent": "eq-scratch-bridge/9.3"})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
        # 不完全な応答をキャッシュしない
        data = json.loads(raw.decode("utf-8"))
        if data.get("type") != "FeatureCollection" or not data.get("features"):
            raise ValueError("震央地名GeoJSONの形式が想定と違うよ")
        path.write_bytes(raw)
        return data
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise ValueError("epicenter_regions.geojson が壊れているよ")
    return data


def point_in_ring(lon, lat, ring):
    """GeoJSONのリング内に点があるか判定する（境界付近は内側扱い）。"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= lon <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= lat <= max(y1, y2) + 1e-9:
            return True
        if (y1 > lat) != (y2 > lat):
            x_cross = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_cross:
                inside = not inside
    return inside


def epicenter_code_from_coordinates(message):
    """Wolfxの震源緯度経度から気象庁の震央地名コードを求める。"""
    lat = num(message.get("Latitude"))
    lon = num(message.get("Longitude"))
    if lat == -1 or lon == -1 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    data = load_epicenter_geojson()
    for feature in data["features"]:
        props = feature.get("properties", {})
        geometry = feature.get("geometry") or {}
        kind, coords = geometry.get("type"), geometry.get("coordinates", [])
        polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
        for polygon in polygons:
            if not polygon or not point_in_ring(lon, lat, polygon[0]):
                continue
            if any(point_in_ring(lon, lat, hole) for hole in polygon[1:]):
                continue
            code = props.get("id")
            name = props.get("name", "")
            if code is not None:
                return f"{int(code):04d}", name
    return None, None


def wolfx_intensity(value):
    """Wolfxの震度文字列を既存の2桁震度コードへ変換する。"""
    text = str(value or "").strip().replace("級", "")
    mapping = {"1": 10, "2": 20, "3": 30, "4": 40,
               "5弱": 45, "5強": 50, "6弱": 55, "6強": 60, "7": 70,
               "5-": 45, "5+": 50, "6-": 55, "6+": 60}
    return mapping.get(text, 0)


def encode_wolfx_eew(message, names, previous=None):
    """Wolfx JMA EEWを、v8と同じ18桁構造に変換する。

    構造: 報数2 + 震央コード4 + M×10 2 + 深さ3 + 推定最大震度2
          + PLUM1 + 最終報1 + 取消1 + 種別2
    種別: 01=予報、02=警報。通常の地震情報03は従来どおり。
    """
    event_id = str(message.get("EventID", ""))
    serial_value = message.get("Serial")
    if serial_value is None and previous:
        serial_value = previous.get("serial", "00")
    try:
        serial = f"{int(serial_value):02d}"[-2:]
    except (TypeError, ValueError):
        serial = "00"

    raw_hypocenter = message.get("Hypocenter", "")
    if isinstance(raw_hypocenter, dict):
        area = raw_hypocenter.get("Area") or {}
        name = str(raw_hypocenter.get("name") or raw_hypocenter.get("Name")
                   or area.get("Name") or area.get("name") or "")
    else:
        name = str(raw_hypocenter or "")

    # 手元の気象庁震央地名コード表を最優先する（行番号=4桁コード）。
    epi = names.get(normalize_epicenter_name(name), "")
    resolved_name = name
    if not epi:
        try:
            geo = load_epicenter_geojson()
            normalized = normalize_epicenter_name(name)
            for feature in geo["features"]:
                props = feature.get("properties", {})
                if normalize_epicenter_name(props.get("name", "")) == normalized and normalized:
                    epi = f"{int(props['id']):04d}"
                    resolved_name = props.get("name", name)
                    break
            if not epi:
                epi, geo_name = epicenter_code_from_coordinates(message)
                if geo_name:
                    resolved_name = geo_name
        except Exception as e:
            print(f"震央GeoJSONの取得・照合に失敗: {e}")
    if not epi:
        epi = names.get(normalize_epicenter_name(name), "")
    if not epi and previous and previous.get("event_id") == event_id:
        epi = previous.get("epicenter", "")
        resolved_name = previous.get("epicenter_name", name)
    if not epi:
        raise ValueError(f"震央コードを特定できないため送信を中止: {name or '震央名不明'}")
    magnitude = num(message.get("Magnitude", message.get("Magunitude")))
    mag = 99 if magnitude < 0 else min(98, int(round(magnitude * 10)))
    depth_value = num(message.get("Depth"))
    depth = 999 if depth_value < 0 else min(998, int(depth_value))
    intensity = wolfx_intensity(message.get("MaxIntensity"))
    # 既存のPLUM欄にはWolfxのisAssumptionを対応づける。
    plum = int(bool(message.get("isAssumption", False)))
    is_warn = bool(message.get("isWarn"))
    kind = 2 if is_warn else 1
    final = int(bool(message.get("isFinal")))
    cancelled = int(bool(message.get("isCancel")))

    # 同一EventID内の予報→警報ではWolfxのSerialをそのまま使用する。
    # Serial欠落時のみ、同一イベントの前回値を引き継ぐ。
    if previous and previous.get("event_id") == event_id and serial == "00":
        serial = previous.get("serial", "00")

    data = {"serial": serial, "epicenter": epi, "epicenter_name": resolved_name,
            "magnitude": mag, "depth": depth, "intensity": intensity,
            "plum": plum, "kind": kind, "event_id": event_id,
            "final": final, "cancelled": cancelled}
    payload = (f"{serial}{epi}{mag:02d}{depth:03d}{intensity:02d}{plum}"
               f"{final}{cancelled}{kind:02d}")
    return payload, data


def wolfx_eew_receiver(out_queue, stop_event):
    """Wolfx WebSocketを維持し、EEW JSONをキューへ渡す。切断時は再接続。"""
    import websocket  # pip install -U websocket-client
    delay = 3
    while not stop_event.is_set():
        ws = None
        try:
            ws = websocket.create_connection(WOLFX_EEW_WS, timeout=20,
                                             enable_multithread=True)
            ws.settimeout(20)
            print("Wolfx EEW WebSocket 接続OK")
            delay = 3
            while not stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # heartbeat待ち。接続が生きているか確認するためpingを送る。
                    ws.send("ping")
                    continue
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if data.get("type") == "heartbeat":
                    try:
                        ws.send("ping")
                    except Exception:
                        break
                    continue
                if data.get("type") == "jma_eew" or "EventID" in data:
                    out_queue.put(data)
        except Exception as e:
            if not stop_event.is_set():
                print(f"Wolfx EEW 接続エラー: {e}。{delay}秒後に再接続")
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        stop_event.wait(delay)
        delay = min(delay * 2, 60)


def encode_eew_state(data, final=0, cancelled=0):
    return (f"{data['serial']}{data['epicenter']}{data['magnitude']:02d}"
            f"{data['depth']:03d}{data['intensity']:02d}{data['plum']}"
            f"{int(final)}{int(cancelled)}{data.get('kind', 2):02d}")


# ---------- 本家Scratchのクラウドへ書き込み ----------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# 送り方の候補。最初に届いた方法を覚えて、次からはそれを最初に使う
#   scratchattach  : ライブラリで送る
#   direct-slow    : 直接WebSocket。ブラウザっぽいヘッダー+ゆっくり送る
#   direct-quoted  : direct-slowに加えて、セッションIDをクッキーで引用符つきにする
#   direct-plain   : 直接WebSocket。最小限の送り方
SEND_METHODS = ["scratchattach", "direct-slow", "direct-quoted", "direct-plain"]


def check_session(sid):
    """セッションIDがScratchに認められているか調べて、ユーザー名を返す(ダメならNone)"""
    try:
        req = urllib.request.Request(
            "https://scratch.mit.edu/session/",
            headers={"User-Agent": BROWSER_UA, "X-Requested-With": "XMLHttpRequest",
                     "Cookie": "scratchsessionsid=" + sid + ";",
                     "Referer": "https://scratch.mit.edu/"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        return (data.get("user") or {}).get("username")
    except Exception as e:
        print("  セッションの確認でエラー:", e)
        return None


class ScratchCloud:
    def __init__(self, project_id):
        self.project_id = str(project_id)
        self.conn = None
        self.username = None
        self.session_id = None
        self.working = None
        self.identity_ready = False

    def _ensure_identity(self):
        if self.identity_ready:
            return
        self.identity_ready = True
        env_user = os.environ.get("SCRATCH_USERNAME")
        self.session_id = os.environ.get("SCRATCH_SESSION_ID")
        real = check_session(self.session_id) if self.session_id else None
        if self.session_id and not real:
            print("  警告: セッションIDがScratchに認められてない。"
                  "ブラウザでログインし直して、セッションIDを取り直してね")
        elif real:
            print(f"  セッション確認OK: {real} としてログイン中")
        self.username = real or env_user

    def _connect_scratchattach(self):
        import scratchattach as sa  # pip install -U scratchattach
        user = os.environ.get("SCRATCH_USERNAME")
        sid = os.environ.get("SCRATCH_SESSION_ID")
        pw = os.environ.get("SCRATCH_PASSWORD")
        if sid:
            if hasattr(sa, "login_by_id"):
                session = sa.login_by_id(sid, username=user)
            else:
                session = sa.Session(sid, username=user)
        elif user and pw:
            session = sa.login(user, pw)
        else:
            raise RuntimeError("SCRATCH_USERNAMEとSCRATCH_SESSION_IDが設定されていない")
        self.username = self.username or getattr(session, "username", None) or user
        self.session_id = self.session_id or getattr(session, "id", None) or sid
        self.conn = session.connect_cloud(self.project_id)

    def _send_direct(self, name, value, quoted, slow, browser_ua):
        if not self.session_id or not self.username:
            raise RuntimeError("直接WebSocket用のログイン情報が足りない")
        import websocket  # pip install -U websocket-client
        cookie_value = self.session_id
        if quoted and not cookie_value.startswith('"'):
            cookie_value = '"' + cookie_value + '"'
        kwargs = dict(cookie="scratchsessionsid=" + cookie_value + ";",
                      origin="https://scratch.mit.edu", timeout=10)
        if browser_ua:
            kwargs["header"] = ["User-Agent: " + BROWSER_UA]
        ws = websocket.create_connection("wss://clouddata.scratch.mit.edu", **kwargs)
        try:
            ws.send(json.dumps({"method": "handshake", "user": self.username,
                                "project_id": self.project_id}) + "\n")
            if slow:
                time.sleep(1.0)
            ws.send(json.dumps({"method": "set", "user": self.username,
                                "project_id": self.project_id,
                                "name": "\u2601 " + name, "value": value}) + "\n")
            time.sleep(1.0 if slow else 0.5)
        finally:
            ws.close()

    def _send(self, method, name, value):
        if method == "scratchattach":
            if self.conn is None:
                self._connect_scratchattach()
            self.conn.set_var(name, value)
        elif method == "direct-plain":
            self._send_direct(name, value, quoted=False, slow=False, browser_ua=False)
        elif method == "direct-slow":
            self._send_direct(name, value, quoted=False, slow=True, browser_ua=True)
        elif method == "direct-quoted":
            self._send_direct(name, value, quoted=True, slow=True, browser_ua=True)
        else:
            raise RuntimeError("知らない送り方: " + method)

    def set_var(self, name, value):
        value = str(value)
        self._ensure_identity()
        before = self._recent_log_signatures(name)
        order = ([self.working] if self.working else []) + \
                [m for m in SEND_METHODS if m != self.working]
        errors = []
        for method in order:
            try:
                self._send(method, name, value)
            except Exception as e:
                errors.append(f"{method}: {type(e).__name__} {e}")
                if method == "scratchattach":
                    self.conn = None
                continue
            if self._wait_for_log(name, value, before):
                if self.working != method:
                    print(f"  MIT Scratch: 「{method}」の送り方で届いたよ。次からこれを先に使うよ")
                self.working = method
                return
            errors.append(f"{method}: 送ったけど履歴に出ない")
        self.working = None
        raise RuntimeError("どの送り方でもMIT側の履歴に出なかった | " + " / ".join(errors))

    def _wait_for_log(self, name, value, before):
        for _ in range(8):
            time.sleep(0.5)
            try:
                logs = self._recent_logs()
            except Exception:
                continue
            if any(log.get("name") == "\u2601 " + name
                   and str(log.get("value")) == str(value)
                   and (not self.username or log.get("user", "").lower() ==
                        self.username.lower())
                   and self._log_signature(log) not in before
                   for log in logs):
                return True
        return False

    def _recent_logs(self):
        url = ("https://clouddata.scratch.mit.edu/logs?projectid="
               + self.project_id + "&limit=100&offset=0")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.load(response)
        return data if isinstance(data, list) else []

    @staticmethod
    def _log_signature(log):
        return (log.get("timestamp"), log.get("user"), log.get("name"),
                str(log.get("value")))

    def _recent_log_signatures(self, name):
        try:
            return {self._log_signature(log) for log in self._recent_logs()
                    if log.get("name") == "\u2601 " + name}
        except Exception:
            return set()


# ---------- TurboWarpのクラウドへ書き込み(予備) ----------
class TwCloud:
    def __init__(self, project_id, user, contact):
        self.project_id = str(project_id)
        self.user = user
        self.ua = f"eq-scratch-bridge/5 (contact: {contact})"

    def set_var(self, name, value):
        import websocket  # pip install websocket-client
        ws = websocket.create_connection(
            TW_URL, header=[f"User-Agent: {self.ua}"], timeout=10)
        try:
            ws.send(json.dumps({"method": "handshake", "user": self.user,
                                "project_id": self.project_id}))
            time.sleep(0.3)
            ws.send(json.dumps({"method": "set", "user": self.user,
                                "project_id": self.project_id,
                                "name": "\u2601 " + name, "value": str(value)}))
            time.sleep(0.3)
        finally:
            ws.close()


# ---------- 両方のクラウドへ同じ値を書き込み ----------
class BothClouds:
    def __init__(self, targets):
        self.fast_targets = [(label, target) for label, target in targets
                             if label == "TurboWarp"]
        self.background_targets = [(label, target) for label, target in targets
                                   if label != "TurboWarp"]
        self.pending = queue.Queue(maxsize=1)
        self.worker = None
        if self.background_targets:
            self.worker = threading.Thread(target=self._send_background,
                                           name="mit-cloud-sender", daemon=True)
            self.worker.start()

    def set_var(self, name, value):
        fast_succeeded = False
        for label, target in self.fast_targets:
            try:
                target.set_var(name, value)
                print(f"  {label}: 送ったよ")
                fast_succeeded = True
            except Exception as e:
                print(f"  {label}: 送信失敗: {e}")
        if self.background_targets:
            try:
                self.pending.put_nowait((name, str(value)))
            except queue.Full:
                try:
                    self.pending.get_nowait()
                    self.pending.task_done()
                except queue.Empty:
                    pass
                self.pending.put_nowait((name, str(value)))
                print("  MIT Scratch: 未送信分を最新データに更新したよ")
            else:
                print("  MIT Scratch: 裏で送信中")
        if not fast_succeeded and not self.background_targets:
            raise RuntimeError("送信先への送信に失敗")

    def wait(self, timeout=120):
        # --once や --test のときは、裏の送信が終わるまで待ってから終了する
        if not self.background_targets:
            return
        done = threading.Event()

        def _join():
            self.pending.join()
            done.set()

        threading.Thread(target=_join, daemon=True).start()
        if not done.wait(timeout):
            print("  MIT Scratch: 送信の完了を待ちきれなかった")

    def _send_background(self):
        while True:
            item = self.pending.get()
            try:
                if item is None:
                    return
                name, value = item
                for label, target in self.background_targets:
                    try:
                        target.set_var(name, value)
                        print(f"  {label}: クラウド履歴で受信確認")
                    except Exception as e:
                        print(f"  {label}: 送信失敗: {e}")
            finally:
                self.pending.task_done()


# ---------- 震央地名コード表 ----------
def make_table():
    names = {}
    for fn in recent_files(150):
        try:
            a = get_json(BASE + fn)["Body"]["Earthquake"]["Hypocenter"]["Area"]
            names[int(a["Code"])] = a["Name"]
        except Exception:
            pass
        time.sleep(0.2)
    with open("epicenter_names.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(names.get(i, "-") for i in range(1, 1000)))
    print(f"epicenter_names.txt を作ったよ({len(names)}地域分)")


# ---------- 1件を送る ----------
def send_file(fn, cloud, var):
    d = get_json(BASE + fn)
    title = str(d.get("Head", {}).get("Title", ""))
    if issue_code(title) != 3:
        print(time.strftime("%H:%M:%S"), fn, "対象外なので送らない:", title)
        return None
    eq = d.get("Body", {}).get("Earthquake", {})
    area = eq.get("Hypocenter", {}).get("Area", {})
    code = encode(d)
    print(time.strftime("%H:%M:%S"), fn)
    print("  地震:", eq.get("OriginTime"), area.get("Name"), "M", eq.get("Magnitude"))
    print("  数字:", code)
    if cloud:
        cloud.set_var(var, code)
        if not isinstance(cloud, BothClouds):
            print("  送ったよ")
    return code


def send_latest(cloud, var):
    for fn in recent_files(40):
        d = get_json(BASE + fn)
        if issue_code(str(d.get("Head", {}).get("Title", ""))) == 3:
            return fn, send_file(fn, cloud, var)
    print("震源・震度情報が見つからなかった")
    return None, None


# ---------- メイン ----------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", choices=["scratch", "turbowarp", "both"], default="turbowarp",
                   help="送信先 (初期設定: turbowarp)")
    p.add_argument("--project", default=os.environ.get("EQ_PROJECT_ID", DEFAULT_PROJECT))
    p.add_argument("--contact", default=os.environ.get("EQ_CONTACT", ""))
    p.add_argument("--user", default=os.environ.get("EQ_USER", ""))
    p.add_argument("--var", default="eqquake")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--eew-interval", type=int, default=EEW_INTERVAL)
    p.add_argument("--test")
    p.add_argument("--test-wolfx", action="store_true",
                   help="Wolfxの最新EEW JSONを1件取得して変換・送信テスト")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--table", action="store_true")
    a = p.parse_args()

    if a.table:
        sys.exit("--table は無効化したよ。手元の epicenter_names.txt を上書きしないでね。")

    if not a.dry and not a.project:
        sys.exit("プロジェクトIDが要るよ。--project か 環境変数 EQ_PROJECT_ID で、自分のプロジェクトIDを指定してね")
    if not a.dry and a.server in ("turbowarp", "both") and a.contact and not a.user:
        sys.exit("TurboWarpに送るときは --user(ユーザー名)も要るよ。環境変数 EQ_USER でもいいよ")

    cloud = None
    if not a.dry:
        if a.server == "scratch":
            cloud = ScratchCloud(a.project)
        elif a.server == "turbowarp":
            if not a.contact:
                sys.exit("TurboWarpに送るときは --contact(連絡先)が要るよ")
            cloud = TwCloud(a.project, a.user, a.contact)
        else:
            targets = []
            username = os.environ.get("SCRATCH_USERNAME")
            if os.environ.get("SCRATCH_SESSION_ID") or (username and os.environ.get("SCRATCH_PASSWORD")):
                targets.append(("MIT Scratch", ScratchCloud(a.project)))
            else:
                print("MIT Scratch: ログイン環境変数がないので今回は送れない。"
                      "SCRATCH_USERNAMEとSCRATCH_PASSWORD (またはSCRATCH_SESSION_ID)を設定してね")
            if a.contact:
                targets.append(("TurboWarp", TwCloud(a.project, a.user, a.contact)))
            if not targets:
                sys.exit("送信先がないよ。Scratchのログイン情報かTurboWarpの連絡先を設定してね")
            cloud = BothClouds(targets)
            print("送信先:", "と".join(label for label, _ in targets))

    if a.test and a.test_wolfx:
        p.error("--test と --test-wolfx は同時に指定できないよ")

    if a.test:
        print("テスト送信:", a.test)
        if cloud:
            cloud.set_var(a.var, a.test)
            if not isinstance(cloud, BothClouds):
                print("送ったよ")
            else:
                cloud.wait()
        return

    if a.test_wolfx:
        print("Wolfx HTTP APIから最新のEEWデータを取得中...")
        try:
            message = get_json(WOLFX_EEW_HTTP)
        except Exception as e:
            sys.exit(f"Wolfx APIの取得に失敗: {type(e).__name__}: {e}")
        if not isinstance(message, dict) or not message:
            sys.exit("Wolfx APIにテスト可能なEEWデータがありません")
        if message.get("isTraining"):
            sys.exit("取得したデータは訓練報なので、誤送信防止のためテストを中止したよ")
        required = ("EventID", "Serial", "Hypocenter", "Magnitude", "Depth", "MaxIntensity")
        missing = [key for key in required if key not in message]
        if missing:
            sys.exit("Wolfx APIの応答に必要な項目がないよ: " + ", ".join(missing))
        names = epicenter_name_codes()
        try:
            payload, cache = encode_wolfx_eew(message, names)
        except ValueError as e:
            sys.exit(f"EEW変換を中止: {e}")
        label = "警報" if cache["kind"] == 2 else "予報"
        print("取得成功:", message.get("AnnouncedTime", "発表時刻不明"))
        print(f"  EEW: {label} / 第{cache['serial']}報 / {cache['epicenter_name'] or message.get('Hypocenter', '震央不明')}")
        print(f"  M{cache['magnitude'] / 10:.1f} / 深さ{cache['depth'] if cache['depth'] != 999 else '不明'}km / 震度コード{cache['intensity']:02d} / isAssumption={bool(message.get('isAssumption', False))}")
        print("  送信データ:", payload, f"({len(payload)}桁)")
        if a.dry:
            print("--dry 指定のため、クラウドには送信していないよ")
        elif cloud:
            cloud.set_var(a.var, payload)
            if not isinstance(cloud, BothClouds):
                print("  クラウドへ送信したよ")
            else:
                cloud.wait()
        return

    if a.once:
        send_latest(cloud, a.var)
        if isinstance(cloud, BothClouds):
            cloud.wait()
        return

    names = epicenter_name_codes()
    if names:
        print(f"補助震央コード表: {len(names)}地域を読み込んだよ")
    print("震央コード: GeoJSONの地名・震源座標から自動判定")

    normal_file, normal_payload = send_latest(cloud, a.var)
    latest = recent_files(1)
    last = latest[0] if latest else normal_file

    eew_queue = queue.Queue()
    eew_stop = threading.Event()
    eew_thread = threading.Thread(target=wolfx_eew_receiver,
                                  args=(eew_queue, eew_stop),
                                  name="wolfx-eew-receiver", daemon=True)
    eew_thread.start()
    print("Wolfx EEW: 新着イベント待機中")

    current_eew = None
    current_event_id = None
    last_eew_report_at = None
    final_at = None
    cancel_at = None

    while True:
        now = time.monotonic()
        try:
            files = recent_files(1)
            if files and files[0] != last:
                payload = send_file(files[0],
                                    None if current_eew is not None or cancel_at is not None else cloud,
                                    a.var)
                if payload:
                    normal_file, normal_payload = files[0], payload
                last = files[0]
        except Exception as e:
            print("通常情報の取得エラー:", e)

        while True:
            try:
                message = eew_queue.get_nowait()
            except queue.Empty:
                break
            if message.get("isTraining"):
                continue
            event_id = str(message.get("EventID", ""))
            previous = current_eew
            if event_id and current_event_id and event_id != current_event_id:
                previous = None
            try:
                payload, cache = encode_wolfx_eew(message, names, previous)
            except ValueError as e:
                print("EEW変換エラー:", e)
                continue
            if message.get("isCancel"):
                # 取消報でも、直前のイベントの数列要素を維持して取消フラグを立てる。
                if previous:
                    cache.update({k: previous.get(k, cache.get(k)) for k in
                                  ("serial", "epicenter", "epicenter_name", "magnitude",
                                   "depth", "intensity", "plum", "kind")})
                    payload = (f"{cache['serial']}{cache['epicenter']}{cache['magnitude']:02d}"
                               f"{cache['depth']:03d}{cache['intensity']:02d}{cache['plum']}"
                               f"0{1}{cache['kind']:02d}")
                current_eew = None
                current_event_id = event_id or current_event_id
                last_eew_report_at = None
                final_at = None
                cancel_at = time.monotonic()
                print(time.strftime("%H:%M:%S"), "EEW 取消報 |", payload)
            else:
                current_eew = cache
                current_event_id = event_id
                last_eew_report_at = time.monotonic()
                final_at = time.monotonic() if cache["final"] else None
                cancel_at = None
                label = "警報" if cache["kind"] == 2 else "予報"
                print(time.strftime("%H:%M:%S"),
                      f"EEW {label} 第{cache['serial']}報 {cache['epicenter_name'] or '震央不明'} | {payload}")
            if cloud:
                cloud.set_var(a.var, payload)
                if not isinstance(cloud, BothClouds):
                    print("  送ったよ")

        now = time.monotonic()
        if current_eew is not None and last_eew_report_at is not None:
            if final_at is None and now - last_eew_report_at >= FINAL_QUIET_SECONDS:
                final_at = now
                payload = encode_eew_state(current_eew, final=1)
                print(time.strftime("%H:%M:%S"), "EEW 最終報(60秒無更新の推定) |", payload)
                if cloud:
                    cloud.set_var(a.var, payload)
                    if not isinstance(cloud, BothClouds):
                        print("  送ったよ")
            elif final_at is not None and now - final_at >= HOLD_SECONDS:
                current_eew = None
                current_event_id = None
                final_at = None
                if normal_payload:
                    print("EEW表示終了。通常情報に戻る |", normal_payload)
                    if cloud:
                        cloud.set_var(a.var, normal_payload)
                        if not isinstance(cloud, BothClouds):
                            print("  送ったよ")

        if cancel_at is not None and now - cancel_at >= HOLD_SECONDS:
            cancel_at = None
            if normal_payload:
                print("キャンセル表示終了。通常情報に戻る |", normal_payload)
                if cloud:
                    cloud.set_var(a.var, normal_payload)
                    if not isinstance(cloud, BothClouds):
                        print("  送ったよ")

        time.sleep(min(1, max(0.2, a.interval / 5)))


main()