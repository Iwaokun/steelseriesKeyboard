import requests
import json
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import threading
import os
import sys
from datetime import datetime, timedelta
from collections import deque

# キーボード入力を監視するためのモジュール
try:
    import keyboard
except ImportError:
    print("keyboardモジュールがインストールされていません。以下のコマンドでインストールしてください：")
    print("pip install keyboard")
    sys.exit(1)

# SteelSeries Engineにリクエストを送信する関数
def send_request(endpoint, payload):
    try:
        core_props_path = "C:\\ProgramData\\SteelSeries\\SteelSeries Engine 3\\coreProps.json"
        with open(core_props_path, "r", encoding='utf-8') as file:
            core_props = json.load(file)
    except FileNotFoundError:
        print("coreProps.jsonが見つかりません。SteelSeries Engineが実行されていますか？")
        print("coreProps.json not found. Is SteelSeries Engine running?")
        return False
    except json.JSONDecodeError:
        print("coreProps.jsonの読み込みに失敗しました。JSON形式を確認してください。")
        print("Failed to parse coreProps.json. Please check the JSON format.")
        return False

    sse_address = f"http://{core_props['address']}/{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(sse_address, headers=headers, data=json.dumps(payload))
    except requests.exceptions.RequestException as e:
        print(f"リクエスト中にエラーが発生しました: {e}")
        print(f"An error occurred during the request: {e}")
        return False

    if response.status_code == 200:
        return True
    else:
        print(f"{endpoint}へのリクエストに失敗しました: {response.status_code}, {response.text}")
        print(f"Failed to send request to {endpoint}: {response.status_code}, {response.text}")
        return False

# ゲームおよびイベントの登録・解除関数
def unregister_event():
    event_metadata = {"game": "EXAMPLE", "event": "KEYBOARD_VISUALIZER"}
    return send_request("remove_game_event", event_metadata)

def unregister_game():
    game_metadata = {"game": "EXAMPLE"}
    return send_request("remove_game", game_metadata)

def register_game():
    game_metadata = {
        "game": "EXAMPLE",
        "game_display_name": "Keyboard Visualizer",
        "developer": "Your Name",
    }
    return send_request("game_metadata", game_metadata)

def register_event():
    event_metadata = {
        "game": "EXAMPLE",
        "event": "KEYBOARD_VISUALIZER",
        "min_value": 0,
        "max_value": 100,          # 必要に応じて調整
        "value_optional": True,    # 動的な画像データを送信するため
    }
    return send_request("register_game_event", event_metadata)

# イベントハンドラーをSteelSeries Engineにバインド（ビットマップ用）
def bind_event_handler_with_bitmap():
    # 初期ビットマップデータとして全黒を設定
    initial_image_data = [0] * 640  # 128x40ピクセルの場合、128*40/8 = 640バイト

    handler = {
        "game": "EXAMPLE",
        "event": "KEYBOARD_VISUALIZER",
        "handlers": [
            {
                "device-type": "screened-128x40",  # ディスプレイの解像度に合わせる
                "zone": "one",
                "mode": "screen",
                "datas": [
                    {
                        "has-text": False,  # テキストを使用しない
                        "image-data": initial_image_data  # 初期ビットマップデータを設定
                    }
                ],
            }
        ],
    }

    return send_request("bind_game_event", handler)

# Pillowを使用して画像をビットマップデータに変換
def image_to_bitmap(image, width=128, height=40):
    img = image.convert('1')  # 白黒画像に変換
    # Pillow >=10.0.0 では Resampling を使用
    try:
        resample_filter = Image.Resampling.LANCZOS
    except AttributeError:
        # Pillow <10.0.0 では ANTIALIAS を使用
        resample_filter = Image.LANCZOS

    img = img.resize((width, height), resample_filter)
    bitmap = []
    for y in range(height):
        for byte in range(width // 8):
            byte_val = 0
            for bit in range(8):
                x = byte * 8 + bit
                pixel = img.getpixel((x, y))
                byte_val = (byte_val << 1) | (1 if pixel else 0)
            bitmap.append(byte_val)
    return bitmap

# ディスプレイをクリアするためのビットマップ
def create_empty_bitmap():
    return [0] * 640

# カスタムビットマップのイベントをSteelSeries Engineに送信
def send_custom_bitmap_event(bitmap, frame_number=1):
    # ビットマップの長さを確認
    if len(bitmap) != 640:
        print(f"ビットマップの長さが不正です: {len(bitmap)} バイト (期待値: 640 バイト)")
        print(f"Invalid bitmap length: {len(bitmap)} bytes (expected: 640 bytes)")
        return False

    payload = {
        "game": "EXAMPLE",
        "event": "KEYBOARD_VISUALIZER",
        "data": {
            "value": frame_number,  # フレーム番号を設定
            "frame": {
                "image-data-128x40": bitmap  # 解像度に合わせたキーを使用
            }
        },
    }

    return send_request("game_event", payload)

# テキストをビットマップにオーバーレイする関数
def overlay_text_on_bitmap(bitmap, width=128, height=40, text="", font_size=20):
    # Pillowを使用して画像を生成
    img = Image.new('1', (width, height), 0)  # 白黒画像、黒で初期化
    draw = ImageDraw.Draw(img)

    # ビットマップデータを画像に描画
    for y in range(height):
        for byte in range(width // 8):
            byte_val = bitmap[y * (width // 8) + byte]
            for bit in range(8):
                x = byte * 8 + bit
                if byte_val & (1 << (7 - bit)):
                    draw.point((x, y), fill=1)

    if text:
        # テキストを最大2行に対応
        lines = text.split('@@')
        lines = lines[:2]  # 最大2行
        lines = [line.strip() for line in lines]

        # フォントの設定
        font = load_japanese_font(size=font_size)
        if font is None:
            print("フォントの読み込みに失敗しました。テキストは表示されません。")
            print("Failed to load font. Text will not be displayed.")
        else:
            # 各行を描画
            for idx, line in enumerate(lines):
                # テキストのバウンディングボックスを取得
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                # テキストを中央に配置
                text_x = (width - text_width) // 2
                # 各行を均等に配置
                total_text_height = text_height * len(lines)
                start_y = (height - total_text_height) // 2
                text_y = start_y + idx * text_height
                draw.text((text_x, text_y), line, font=font, fill=1)

    # Pillow画像をビットマップデータに変換
    new_bitmap = image_to_bitmap(img, width, height)
    return new_bitmap

# 日本語フォントをロードする関数
def load_japanese_font(size=20):
    # Windowsの日本語フォントの一般的なパス
    possible_font_paths = [
        "C:\\Windows\\Fonts\\msgothic.ttc",
        "C:\\Windows\\Fonts\\yugothic.ttc",
        "C:\\Windows\\Fonts\\YuGothicUI.ttf",
        "C:\\Windows\\Fonts\\arialuni.ttf",  # Arial Unicode MS
    ]

    for font_path in possible_font_paths:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, size)
                return font
            except Exception as e:
                print(f"フォント {font_path} の読み込みに失敗しました: {e}")
                print(f"Failed to load font {font_path}: {e}")
    print("日本語フォントが見つかりませんでした。")
    print("Japanese font not found.")
    return None

# WPM（Words Per Minute）計測クラス
class WPMCounter:
    def __init__(self, reset_seconds=10):
        self.key_presses = deque()  # 各キー入力のタイムスタンプを保持
        self.reset_seconds = reset_seconds
        self.lock = threading.Lock()

    def add_key_press(self):
        with self.lock:
            now = datetime.now()
            self.key_presses.append(now)
            self._remove_old_key_presses()

    def _remove_old_key_presses(self):
        cutoff = datetime.now() - timedelta(seconds=self.reset_seconds)
        while self.key_presses and self.key_presses[0] < cutoff:
            self.key_presses.popleft()

    def get_wpm(self):
        with self.lock:
            self._remove_old_key_presses()
            key_count = len(self.key_presses)
            # WPM = (key_count / 5) / (reset_seconds / 60)
            # 一般的なWPM定義では、1ワード = 5キー入力と仮定
            wpm = (key_count / 5) / (self.reset_seconds / 60)
            return int(wpm)

# キーボード入力を監視し、テキストをバッファに追加・削除する関数
def keyboard_listener(buffer, lock, stop_event, wpm_counter=None, removed_chars_stack=None):
    def on_press(event):
        if event.name == 'backspace':
            with lock:
                if buffer:
                    removed_char = buffer.pop()
                    if removed_chars_stack is not None:
                        removed_chars_stack.append(removed_char)
            # バックスペースキーはWPMカウントに含めない
            return
        elif event.name == 'space':
            char = ' '
            count_wpm = False
        elif len(event.name) > 1:
            # その他の特殊キーは無視
            return
        else:
            char = event.name
            count_wpm = True

        with lock:
            buffer.append(char)
            # バッファのサイズを制限（100文字）
            if len(buffer) > 100:
                buffer.pop(0)
            # 新しいキー入力がある場合、削除スタックをクリア
            if removed_chars_stack is not None:
                removed_chars_stack.clear()

        if wpm_counter and count_wpm:
            wpm_counter.add_key_press()

    keyboard.on_press(on_press)

    while not stop_event.is_set():
        time.sleep(0.1)

    keyboard.unhook_all()

# アニメーションの実行
def run_visualizer(keyboard_buffer, buffer_lock, stop_event, wpm_counter):
    frame_number = 1
    width, height = 128, 40
    uppercase = True
    font_size = 20
    show_wpm = True

    try:
        while not stop_event.is_set():
            # キーボード入力モード
            with buffer_lock:
                current_text = ''.join(keyboard_buffer[-10:])  # 最新の10文字を取得
            if uppercase:
                current_text = current_text.upper()

            # WPMの計測
            current_wpm = wpm_counter.get_wpm()
            # テキストのレイアウト
            if show_wpm and current_wpm > 0:
                display_lines = [f"WPM: {current_wpm}", current_text]
            else:
                display_lines = [current_text]

            # テキストの結合（2行の場合は@@で区切る）
            display_text_to_show = "@@".join(display_lines)

            # ビットマップにテキストを追加
            bitmap = overlay_text_on_bitmap(create_empty_bitmap(), width, height, display_text_to_show, font_size=font_size)

            # ビットマップを送信
            success = send_custom_bitmap_event(bitmap, frame_number)
            if not success:
                print("フレームの送信に失敗しました。アニメーションを中断します。")
                print("Failed to send frame. Aborting animation.")
                break

            frame_number += 1
            if frame_number > 1000:
                frame_number = 1
            time.sleep(0.05)  # 20 FPS
    except KeyboardInterrupt:
        print("アニメーションを手動で停止しました。")
        print("Animation stopped manually.")
    finally:
        # ディスプレイをクリア
        empty_bitmap = create_empty_bitmap()
        # テキストをクリアするために空白のテキストをオーバーレイ
        empty_bitmap = overlay_text_on_bitmap(empty_bitmap, width, height, "", font_size=font_size)
        send_custom_bitmap_event(empty_bitmap)
        print("ディスプレイをクリアしました。")
        print("Display cleared.")

# ストップ用のイベント
stop_event = threading.Event()

# メイン関数
def main():
    # キーボード入力のバッファとロック
    keyboard_buffer = []
    buffer_lock = threading.Lock()
    removed_chars_stack = []  # 削除された文字を保存するスタック

    # WPMCounterを一つだけインスタンス化
    wpm_counter = WPMCounter(reset_seconds=10)

    # 登録をクリーンアップ
    if not unregister_event():
        print("イベントの解除に失敗しました。続行します。")
        print("Failed to unregister event. Continuing.")
    if not unregister_game():
        print("ゲームの解除に失敗しました。続行します。")
        print("Failed to unregister game. Continuing.")

    # 新しいゲームとイベントを登録
    if not register_game():
        print("ゲームの登録に失敗しました。終了します。")
        print("Failed to register game. Exiting.")
        return
    if not register_event():
        print("イベントの登録に失敗しました。終了します。")
        print("Failed to register event. Exiting.")
        return

    # ハンドラーをバインド
    if not bind_event_handler_with_bitmap():
        print("ハンドラーのバインドに失敗しました。終了します。")
        print("Failed to bind event handler. Exiting.")
        return

    # 登録が反映されるまで待機
    print("設定が反映されるまで2秒待機します。 / Waiting 2 seconds for settings to apply.")
    time.sleep(2)

    # キーボードリスナーのスレッドを開始
    keyboard_thread = threading.Thread(target=keyboard_listener, args=(
        keyboard_buffer, buffer_lock, stop_event, wpm_counter, removed_chars_stack))
    keyboard_thread.start()

    # アニメーションスレッドの開始
    anim_thread = threading.Thread(target=run_visualizer, args=(
        keyboard_buffer, buffer_lock, stop_event, wpm_counter))
    anim_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("プログラムを停止します。 / Stopping the program.")
    finally:
        stop_event.set()
        anim_thread.join()

        # キーボードリスナーを停止
        if keyboard_thread:
            keyboard_thread.join()

        # ディスプレイをクリア
        empty_bitmap = create_empty_bitmap()
        # テキストをクリアするために空白のテキストをオーバーレイ
        empty_bitmap = overlay_text_on_bitmap(empty_bitmap, 128, 40, "", font_size=20)
        send_custom_bitmap_event(empty_bitmap)
        print("ディスプレイをクリアしました。 / Display cleared.")

if __name__ == "__main__":
    main()
