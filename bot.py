# ============================================================
# BeB Price Monitor + Telegram (Persistent Settings Button)
# ============================================================

import re
import json
import time
import threading
import requests
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

CONFIG_FILE = Path(__file__).parent / "id.txt"
CHATS_FILE = Path(__file__).parent / "chats.json"

TELEGRAM_TOKEN = None
TELEGRAM_CHAT_IDS = []

AWAITING_INTERVAL = set()

INTERVAL = 60
INTERVAL_LOCK = threading.Lock()

LAST_PRICES = None
LAST_TIME = None
LAST_LOCK = threading.Lock()

URL = (
    "https://www.technolife.com/product-479639/"
    "%D9%BE%D9%84%DB%8C-%D8%A7%D8%B3%D8%AA%DB%8C%D8%B4%D9%86-5-"
    "%D8%A7%D8%B3%D9%84%DB%8C%D9%85-%D8%AF%DB%8C%D8%AC%DB%8C%D8%AA%D8%A7%D9%84-"
    "%D8%A7%D8%B1%D9%88%D9%BE%D8%A7-cfi-2116-"
)

OUTPUT = Path("price_history.txt")
CATEGORIES = ["نقدی", "اقساطی", "اعتباری"]

NOISE = [
    "ارزیابی عملکرد", "تامین کالا", "تحویل به موقع", "بدون مرجوعی",
    "ارسال فوری", "ارسال زیر ۳ ساعت", "موجود در انبار", "گارانتی شرکتی",
    "افزودن به سبد خرید", "مشاهده بیشتر", "عالی", "تومان",
]


# ============================================================
# ذخیره/بازیابی chat ها
# ============================================================

def load_chats():
    global TELEGRAM_CHAT_IDS
    if CHATS_FILE.exists():
        try:
            TELEGRAM_CHAT_IDS = json.loads(CHATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            TELEGRAM_CHAT_IDS = []


def save_chats():
    CHATS_FILE.write_text(
        json.dumps(TELEGRAM_CHAT_IDS, ensure_ascii=False),
        encoding="utf-8",
    )


def add_chat(chat_id):
    if chat_id not in TELEGRAM_CHAT_IDS:
        TELEGRAM_CHAT_IDS.append(chat_id)
        save_chats()
        print(f"[+] Chat added: {chat_id}")


# ============================================================
# تنظیمات
# ============================================================

def load_config():
    global TELEGRAM_TOKEN

    if not CONFIG_FILE.exists():
        print(f"[!] Config file not found: {CONFIG_FILE}")
        return False

    raw = CONFIG_FILE.read_text(encoding="utf-8")
    m = re.search(r'TELEGRAM_TOKEN\s*=\s*["\']([^"\']+)["\']', raw)
    if m:
        TELEGRAM_TOKEN = m.group(1).strip()

    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "PUT_TOKEN_HERE":
        print("[!] TELEGRAM_TOKEN not set in id.txt")
        return False

    load_chats()
    print(f"[+] Token OK. Chats: {TELEGRAM_CHAT_IDS}")
    return True


# ============================================================
# تلگرام API
# ============================================================

def send_message(chat_id, text, keyboard=None, reply_keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    for idx, chunk in enumerate(chunks):
        data = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if keyboard and idx == len(chunks) - 1:
            data["reply_markup"] = json.dumps(keyboard)
        elif reply_keyboard and idx == len(chunks) - 1:
            data["reply_markup"] = json.dumps(reply_keyboard)

        try:
            requests.post(url, data=data, timeout=15)
        except Exception as e:
            print(f"[!] send failed to {chat_id}: {e}")


def broadcast(text):
    for chat_id in list(TELEGRAM_CHAT_IDS):
        send_message(chat_id, text)


def edit_message(chat_id, message_id, text, keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    try:
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        print(f"[!] edit failed: {e}")


def answer_callback(callback_id, text=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, data={"callback_query_id": callback_id, "text": text}, timeout=10)
    except Exception:
        pass


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=35)
        return r.json()
    except Exception:
        return {"ok": False, "result": []}


# ============================================================
# منوها
# ============================================================

def reply_keyboard():
    return {
        "keyboard": [
            [{"text": "⚙️ تنظیمات"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "⚙️ تغییر زمان بررسی", "callback_data": "set_interval"}],
            [{"text": "📊 دریافت آخرین قیمت‌ها", "callback_data": "get_prices"}],
        ]
    }


def back_menu():
    return {
        "inline_keyboard": [
            [{"text": "🔙 بازگشت به منو", "callback_data": "menu"}],
        ]
    }


def cancel_menu():
    return {
        "inline_keyboard": [
            [{"text": "❌ انصراف", "callback_data": "menu"}],
        ]
    }


# ============================================================
# دستورات
# ============================================================

def handle_start(chat_id):
    add_chat(chat_id)
    send_message(
        chat_id,
        "👋 سلام!\n"
        "این ربات قیمت PS5 Slim Digital CFI-2116 رو رصد می‌کنه.\n\n"
        "برای دسترسی به تنظیمات از دکمه پایین استفاده کن.",
        reply_keyboard=reply_keyboard(),
    )

    with LAST_LOCK:
        prices = LAST_PRICES
        when = LAST_TIME

    if prices:
        send_message(chat_id, f"📊 آخرین قیمت‌ها (ساعت {when}):\n{format_report(prices)}")
    else:
        send_message(chat_id, "⏳ هنوز قیمتی ثبت نشده. اولین بررسی در حال انجامه.")


def show_settings(chat_id):
    with INTERVAL_LOCK:
        sec = INTERVAL
    send_message(
        chat_id,
        f"⚙️ تنظیمات\n\n"
        f"⏱ زمان فعلی بررسی: هر {sec // 60} دقیقه\n\n"
        f"یکی از گزینه‌ها رو انتخاب کن:",
        keyboard=main_menu(),
        reply_keyboard=reply_keyboard(),
    )


def handle_text(chat_id, text):
    global INTERVAL

    if chat_id in AWAITING_INTERVAL:
        AWAITING_INTERVAL.discard(chat_id)
        m = re.fullmatch(r"\s*(\d+)\s*", text)
        if not m:
            send_message(
                chat_id,
                "⚠️ عدد معتبر به دقیقه بفرست. مثال: 10",
                keyboard=cancel_menu(),
                reply_keyboard=reply_keyboard(),
            )
            AWAITING_INTERVAL.add(chat_id)
            return

        minutes = int(m.group(1))
        if minutes < 1:
            send_message(chat_id, "⚠️ حداقل ۱ دقیقه.", reply_keyboard=reply_keyboard())
            return
        if minutes > 1440:
            send_message(chat_id, "⚠️ حداکثر ۱۴۴۰ دقیقه (۲۴ ساعت).", reply_keyboard=reply_keyboard())
            return

        with INTERVAL_LOCK:
            INTERVAL = minutes * 60

        send_message(
            chat_id,
            f"✅ زمان بررسی به {minutes} دقیقه تغییر کرد.",
            reply_keyboard=reply_keyboard(),
        )
        return

    if text.startswith("/start"):
        handle_start(chat_id)
        return

    if "تنظیمات" in text:
        show_settings(chat_id)
        return

    show_settings(chat_id)


def handle_callback(callback):
    global INTERVAL

    chat_id = str(callback["message"]["chat"]["id"])
    message_id = callback["message"]["message_id"]
    data = callback.get("data", "")

    if data == "menu":
        AWAITING_INTERVAL.discard(chat_id)
        with INTERVAL_LOCK:
            sec = INTERVAL
        edit_message(
            chat_id, message_id,
            f"⚙️ تنظیمات\n\n"
            f"⏱ زمان فعلی بررسی: هر {sec // 60} دقیقه\n\n"
            f"یکی از گزینه‌ها رو انتخاب کن:",
            keyboard=main_menu(),
        )
        answer_callback(callback["id"])
        return

    if data == "set_interval":
        with INTERVAL_LOCK:
            sec = INTERVAL
        AWAITING_INTERVAL.add(chat_id)
        edit_message(
            chat_id, message_id,
            f"⏱ زمان فعلی بررسی: هر {sec // 60} دقیقه ({sec} ثانیه)\n\n"
            f"زمان جدید رو به دقیقه بفرست (مثلاً 10):",
            keyboard=cancel_menu(),
        )
        answer_callback(callback["id"])
        return

    if data == "get_prices":
        with LAST_LOCK:
            prices = LAST_PRICES
            when = LAST_TIME
        if prices:
            edit_message(
                chat_id, message_id,
                f"📊 آخرین قیمت‌ها (ساعت {when}):\n{format_report(prices)}",
                keyboard=back_menu(),
            )
        else:
            edit_message(
                chat_id, message_id,
                "⏳ هنوز قیمتی ثبت نشده.",
                keyboard=back_menu(),
            )
        answer_callback(callback["id"])
        return

    answer_callback(callback["id"])


# ============================================================
# polling تلگرام
# ============================================================

def telegram_polling():
    offset = None
    print("[+] Telegram polling started.")

    while True:
        data = get_updates(offset)
        if not data.get("ok"):
            time.sleep(5)
            continue

        for update in data.get("result", []):
            offset = update["update_id"] + 1

            if "callback_query" in update:
                handle_callback(update["callback_query"])
                continue

            msg = update.get("message")
            if not msg:
                continue

            chat_id = str(msg["chat"]["id"])
            text = msg.get("text", "")

            handle_text(chat_id, text)


# ============================================================
# استخراج قیمت
# ============================================================

def normalize_digits(text):
    return text.translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    ))


def get_category(text, section):
    if "اعتباری" in text:
        return "اعتباری"
    if "اقساطی" in text or "اقساط" in text:
        return "اقساطی"
    return section if section in CATEGORIES else "نقدی"


def clean_name(text):
    text = re.sub(r"^[*•\-\s]+", "", text)
    text = re.sub(r"\s+(اقساطی|اعتباری|اقساط)\s*", " ", text)
    return text.strip()


def expand_all_sellers(page):
    for _ in range(20):
        buttons = page.get_by_text("مشاهده بیشتر", exact=True)
        if buttons.count() == 0:
            break
        before = page.locator("body").inner_text()
        try:
            buttons.first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception:
            break
        after = page.locator("body").inner_text()
        if before == after:
            break


def parse_card(lines, section):
    if not lines:
        return None

    price = None
    for line in lines:
        line = normalize_digits(line).strip()
        if re.fullmatch(r"[\d,]+", line):
            v = int(line.replace(",", ""))
            if v >= 1_000_000:
                price = v
        m = re.search(r"([\d,]{7,})\s*تومان", line)
        if m:
            v = int(m.group(1).replace(",", ""))
            if v >= 1_000_000:
                price = v

    if price is None:
        return None

    title = None
    for line in lines[:12]:
        raw = re.sub(r"^[*•\-\s]+", "", line).strip()
        if not raw:
            continue
        if any(item in raw for item in NOISE):
            continue
        if re.search(r"\d{6,}", raw):
            continue
        if raw in ["نقدی", "اقساطی", "اعتباری"]:
            continue
        if "ارزیابی" in raw or "فروشندگان" in raw:
            continue
        title = raw
        break

    if not title:
        return None

    return get_category(title, section), clean_name(title), price


def extract_prices(page):
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    expand_all_sellers(page)

    text = normalize_digits(page.locator("body").inner_text())
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    results = {c: {} for c in CATEGORIES}
    start = next((i for i, l in enumerate(lines) if "همه فروشندگان" in l), None)
    if start is None:
        raise RuntimeError("All sellers section not found")

    section = "نقدی"
    card = []

    def save(card_lines, sec):
        r = parse_card(card_lines, sec)
        if r:
            cat, name, price = r
            results[cat][name] = price

    for line in lines[start + 1:]:
        if "فروشندگان طرف قرارداد اقساطی" in line and "اعتباری" not in line:
            if card:
                save(card, section)
                card = []
            section = "اقساطی"
            continue
        if "فروشندگان طرف قرارداد اعتباری" in line:
            if card:
                save(card, section)
                card = []
            section = "اعتباری"
            continue
        card.append(line)
        if "افزودن به سبد خرید" in line:
            save(card, section)
            card = []

    if card:
        save(card, section)

    if sum(len(s) for s in results.values()) == 0:
        raise RuntimeError("No sellers extracted.")

    return results


def format_report(prices):
    out = []
    for cat in CATEGORIES:
        sellers = prices[cat]
        out.append(f"\n========== {cat} ==========")
        if not sellers:
            out.append("موردی ثبت نشد")
            continue
        for name, price in sellers.items():
            out.append(f"{name} | {price:,} تومان")
        out.append(f"تعداد: {len(sellers)}")
    return "\n".join(out)


def write_log(message):
    with OUTPUT.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


# ============================================================
# مانیتور
# ============================================================

def monitor_loop():
    global LAST_PRICES, LAST_TIME
    previous_prices = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="fa-IR")

        try:
            while True:
                with INTERVAL_LOCK:
                    interval = INTERVAL

                now = datetime.now().strftime("%H:%M:%S")

                try:
                    current = extract_prices(page)

                    if previous_prices is None:
                        msg = (
                            f"\n{'=' * 55}\nساعت: {now}\nثبت اولیه\n"
                            f"{format_report(current)}\n{'=' * 55}"
                        )
                        tg = f"✅ ثبت اولیه — {now}\n{format_report(current)}"
                        status = "initial"

                    elif current == previous_prices:
                        msg = f"\nساعت: {now} | بدون تغییر"
                        tg = f"⏱ {now} | بدون تغییر"
                        status = "no-change"

                    else:
                        diffs = []
                        for cat in CATEGORIES:
                            old = previous_prices.get(cat, {})
                            new = current.get(cat, {})
                            for name in new:
                                if name not in old:
                                    diffs.append(f"+ {name} ({cat}): {new[name]:,}")
                                elif new[name] != old[name]:
                                    diffs.append(f"~ {name} ({cat}): {old[name]:,} → {new[name]:,}")
                            for name in old:
                                if name not in new:
                                    diffs.append(f"- {name} ({cat}): حذف شد")
                        diff_text = "\n".join(diffs) if diffs else "تغییر جزئی"
                        msg = (
                            f"\n{'=' * 55}\nساعت: {now}\nتغییر قیمت\n"
                            f"{format_report(current)}\n{'=' * 55}"
                        )
                        tg = f"🔔 تغییر قیمت — {now}\n\n{diff_text}\n\n{format_report(current)}"
                        status = "changed"

                    write_log(msg)

                    with LAST_LOCK:
                        LAST_PRICES = current
                        LAST_TIME = now

                    broadcast(tg)
                    print(f"[{now}] {status}")

                    previous_prices = {k: v.copy() for k, v in current.items()}

                except Exception as e:
                    write_log(f"\nساعت: {now} | خطا: {e}")
                    broadcast(f"❌ خطا — {now}\n{e}")
                    print(f"[{now}] error: {e}")

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\nMonitor stopped.")

        finally:
            browser.close()


# ============================================================
# main
# ============================================================

def main():
    if not load_config():
        return

    print("=" * 40)
    print("BeB Price Monitor")
    print(f"Interval: {INTERVAL}s | Chats: {len(TELEGRAM_CHAT_IDS)}")
    print("=" * 40)

    threading.Thread(target=telegram_polling, daemon=True).start()
    monitor_loop()


if __name__ == "__main__":
    main()