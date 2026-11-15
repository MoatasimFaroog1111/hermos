import argparse
import os
import sys
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_DIRECT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

TIKTOK_CAPTION = (
    "أطلقنا متجر Luma Store ✦ منتجات رقمية فاخرة لتنظيم حياتك وإدارة مشاريعك "
    "— بتسليم فوري ونسختين (عربية وإنجليزية) مع كل منتج. الرابط في البايو ✦ "
    "#LumaStore #منتجات_رقمية #تنظيم_الوقت #إنتاجية #تخطيط"
)


def update_env_values(updates: dict[str, str]) -> None:
    """تحديث القيم داخل ملف .env مع الحفاظ على الترميز النظيف UTF-8 بدون BOM."""
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def run_oauth_setup() -> None:
    """الحصول على Access Token و Refresh Token لمرة واحدة عبر المتصفح."""
    load_dotenv()
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "https://luma-store-six.vercel.app/").strip()

    if not client_key or not client_secret:
        raise EnvironmentError(
            "يرجى تعبئة TIKTOK_CLIENT_KEY و TIKTOK_CLIENT_SECRET في ملف .env أولاً."
        )

    params = {
        "client_key": client_key,
        "scope": "video.upload,video.publish",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": "luma_auth_2026",
    }
    auth_link = f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n1. افتح الرابط التالي في متصفحك وسجّل الدخول بحساب تيك توك الخاص بالمتجر:\n")
    print(auth_link)
    print(
        "\n2. بعد الموافقة، سيعيدك المتصفح إلى رابط متجرك وفي نهايته (?code=...)."
        "\n   انسخ الرابط الكامل من شريط العنوان في المتصفح والصقه هنا:\n"
    )

    redirected_url = input("الرابط الكامل بعد التحويل: ").strip()
    parsed = urllib.parse.urlparse(redirected_url)
    code_list = urllib.parse.parse_qs(parsed.query).get("code")

    if not code_list:
        raise ValueError("لم يتم العثور على رمز code في الرابط الملصق. تأكد من نسخ الرابط كاملاً.")

    code = urllib.parse.unquote(code_list[0])
    resp = requests.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"فشل استخراج التوكن من تيك توك: {data}")

    update_env_values(
        {
            "TIKTOK_ACCESS_TOKEN": data["access_token"],
            "TIKTOK_REFRESH_TOKEN": data.get("refresh_token", ""),
        }
    )
    print("\n✓ تم حفظ TIKTOK_ACCESS_TOKEN و TIKTOK_REFRESH_TOKEN في ملف .env بنجاح.")


def refresh_token_if_needed() -> str:
    """تجديد التوكن تلقائياً باستخدام Refresh Token."""
    load_dotenv()
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("TIKTOK_REFRESH_TOKEN", "").strip()

    if not (client_key and client_secret and refresh_token):
        raise EnvironmentError("بيانات تجديد التوكن ناقصة. شغّل السكربت مع --auth أولاً.")

    resp = requests.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"تعذر تجديد التوكن، أعد المصادقة عبر --auth: {data}")

    update_env_values(
        {
            "TIKTOK_ACCESS_TOKEN": data["access_token"],
            "TIKTOK_REFRESH_TOKEN": data.get("refresh_token", refresh_token),
        }
    )
    return data["access_token"]


def upload_to_tiktok(
    video_path: Path,
    mode: str = "inbox",
    privacy: str = "SELF_ONLY",
    dry_run: bool = False,
) -> None:
    """رفع الفيديو إلى تيك توك (إلى مسودات التطبيق inbox أو نشر مباشر direct)."""
    if not video_path.exists():
        raise FileNotFoundError(f"ملف الفيديو غير موجود: {video_path}")

    file_size = video_path.stat().st_size

    print("\n--- معاينة النشر على TikTok ---")
    print(f"• ملف الفيديو : {video_path.name} ({file_size:,} بايت)")
    print(f"• وضع الإرسال : {'مسودة في التطبيق (Inbox)' if mode == 'inbox' else f'نشر مباشر ({privacy})'}")
    print(f"• الوصف المقترح:\n{TIKTOK_CAPTION}")
    print("--------------------------------")

    if dry_run:
        print("وضع المحاكاة (Dry Run): الملف والإعدادات سليمة وجاهزة للرفع.")
        return

    confirm = input("\nهل تؤكد رفع الفيديو إلى تيك توك الآن؟ (y/N): ").strip().lower()
    if confirm != "y":
        print("تم إلغاء العملية.")
        return

    load_dotenv()
    access_token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise EnvironmentError("TIKTOK_ACCESS_TOKEN غير موجود. نفّذ الأمر: python publish_tiktok.py --auth")

    init_url = TIKTOK_INBOX_INIT_URL if mode == "inbox" else TIKTOK_DIRECT_INIT_URL
    payload = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        }
    }
    if mode == "direct":
        payload["post_info"] = {
            "title": TIKTOK_CAPTION[:150],
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    init_resp = requests.post(init_url, headers=headers, json=payload, timeout=30)
    if init_resp.status_code == 401:
        print("انتهت صلاحية التوكن، جاري التجديد تلقائياً...")
        access_token = refresh_token_if_needed()
        headers["Authorization"] = f"Bearer {access_token}"
        init_resp = requests.post(init_url, headers=headers, json=payload, timeout=30)

    init_data = init_resp.json()
    error_info = init_data.get("error", {})
    if error_info.get("code") not in (None, "ok"):
        raise RuntimeError(f"رفض تيك توك تهيئة الرفع: {init_data}")

    upload_url = init_data["data"]["upload_url"]
    publish_id = init_data["data"]["publish_id"]

    print(f"جاري رفع الفيديو (publish_id: {publish_id})...")
    with video_path.open("rb") as f:
        video_bytes = f.read()

    put_headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
    }
    put_resp = requests.put(upload_url, headers=put_headers, data=video_bytes, timeout=120)
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(f"فشل رفع ملف الفيديو ({put_resp.status_code}): {put_resp.text}")

    print("\n✓ تم رفع الفيديو إلى تيك توك بنجاح!")
    if mode == "inbox":
        print("افتح إشعارات تطبيق TikTok على جوالك الآن، الصق الوصف أعلاه، واضغط نشر.")


def main() -> None:
    parser = argparse.ArgumentParser(description="أتمتة رفع فيديو إطلاق Luma Store على TikTok.")
    parser.add_argument("--auth", action="store_true", help="ربط الحساب واستخراج توكن تيك توك.")
    parser.add_argument("--media", type=Path, default=Path("launch_video.mp4"), help="مسار ملف الفيديو.")
    parser.add_argument("--mode", choices=["inbox", "direct"], default="inbox", help="inbox للمسودة، direct للنشر المباشر.")
    parser.add_argument("--privacy", default="SELF_ONLY", help="خصوصية النشر المباشر (SELF_ONLY أو PUBLIC_TO_EVERYONE).")
    parser.add_argument("--publish", action="store_true", help="تفعيل النشر الفعلي مع طلب الموافقة الصريحة.")
    parser.add_argument("--dry-run", action="store_true", help="فحص الملف دون رفع فعلي.")
    args = parser.parse_args()

    try:
        if args.auth:
            run_oauth_setup()
        else:
            upload_to_tiktok(
                video_path=args.media,
                mode=args.mode,
                privacy=args.privacy,
                dry_run=(not args.publish) or args.dry_run,
            )
    except Exception as exc:
        print(f"تعذر إتمام العملية: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
