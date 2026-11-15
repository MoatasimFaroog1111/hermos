import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import tweepy
from dotenv import load_dotenv


LAUNCH_THREAD: List[str] = [
    (
        "أطلقنا اليوم متجر Luma Store ✦\n\n"
        "وجهتك للمنتجات الرقمية المصممة بعناية لتنظيم حياتك وإدارة مشاريعك — "
        "بتسليم فوري ونسختين (عربية وإنجليزية) مع كل منتج.\n\n"
        "تصفّح المنتجات وعاين صفحاتها الداخلية مباشرة قبل الشراء:\n"
        "https://luma-store-six.vercel.app/"
    ),
    (
        "ماذا ستجد داخل المتجر؟\n\n"
        "• منظم الحياة والأهداف (120+ صفحة)\n"
        "• مفكرة الصفاء الذهني\n"
        "• حزمة أوامر الذكاء الاصطناعي (500+ أمر)\n"
        "• قوالب الميزانية الذكية لـ Excel و Sheets\n"
        "• حقيبة صناعة المحتوى (220 فكرة وقالب)\n"
        "• حزمة كتب العمل الحر (5 أدلة عملية)"
    ),
    (
        "أو اختصر الطريق مع المجموعة الكاملة من Luma ✦\n\n"
        "احصل على المنتجات الستة كاملةً في عملية شراء واحدة (باللغتين العربية والإنجليزية) "
        "بـ $59 بدلاً من $111 لو اشتريتها منفردة — بتوفير $52.\n\n"
        "حمّل ملفاتك فوراً واحتفظ بها لك للأبد:\n"
        "https://luma-store-six.vercel.app/"
    ),
]


def load_x_clients() -> tuple[tweepy.Client, tweepy.API]:
    load_dotenv()

    required_keys = [
        "X_API_KEY",
        "X_API_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    ]
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise EnvironmentError(
            f"المفاتيح التالية مفقودة في ملف .env: {', '.join(missing)}"
        )

    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    client_v2 = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )

    auth = tweepy.OAuth1UserHandler(
        api_key, api_secret, access_token, access_token_secret
    )
    api_v1 = tweepy.API(auth)

    return client_v2, api_v1


def upload_media(api_v1: tweepy.API, media_path: Path) -> str:
    if not media_path.exists():
        raise FileNotFoundError(f"ملف الوسائط غير موجود في المسار: {media_path}")

    suffix = media_path.suffix.lower()
    is_video = suffix in {".mp4", ".mov"}

    print(f"جاري رفع الملف: {media_path.name} ...")
    if is_video:
        media = api_v1.media_upload(
            filename=str(media_path),
            media_category="tweet_video",
            chunked=True,
        )
    else:
        media = api_v1.media_upload(filename=str(media_path))

    print(f"تم رفع الوسائط بنجاح (media_id: {media.media_id_string})")
    return media.media_id_string


def validate_tweets(tweets: List[str]) -> None:
    for idx, text in enumerate(tweets, start=1):
        effective_len = len(text)
        if "https://" in text:
            for word in text.split():
                if word.startswith("https://"):
                    effective_len = effective_len - len(word) + 23
        if effective_len > 280:
            raise ValueError(
                f"التغريدة رقم {idx} تتجاوز الحد المسموح (280 حرفاً). الطول الفعلي: {effective_len}"
            )


def publish_thread(
    tweets: List[str],
    media_path: Optional[Path] = None,
    dry_run: bool = False,
    delay_seconds: float = 2.0,
) -> None:
    validate_tweets(tweets)

    print("\n--- معاينة السلسلة قبل النشر ---")
    for idx, text in enumerate(tweets, start=1):
        print(f"\n[تغريدة {idx}/{len(tweets)}]\n{text}")
        if idx == 1 and media_path:
            print(f"[مرفق]: {media_path}")
    print("\n--------------------------------")

    if dry_run:
        print("وضع المحاكاة (Dry Run): تم التحقق من النصوص بنجاح دون نشر فعلي.")
        return

    confirm = input("\nهل تؤكد نشر هذه السلسلة الآن على حسابك في X؟ (y/N): ").strip().lower()
    if confirm != "y":
        print("تم إلغاء عملية النشر.")
        return

    client_v2, api_v1 = load_x_clients()

    first_media_ids: Optional[List[str]] = None
    if media_path:
        media_id = upload_media(api_v1, media_path)
        first_media_ids = [media_id]

    previous_tweet_id: Optional[str] = None

    for idx, text in enumerate(tweets, start=1):
        kwargs = {"text": text}
        if idx == 1 and first_media_ids:
            kwargs["media_ids"] = first_media_ids
        if previous_tweet_id:
            kwargs["in_reply_to_tweet_id"] = previous_tweet_id

        response = client_v2.create_tweet(**kwargs)
        tweet_id = str(response.data["id"])
        previous_tweet_id = tweet_id

        print(f"تم نشر التغريدة {idx}/{len(tweets)}: https://x.com/i/web/status/{tweet_id}")

        if idx < len(tweets):
            time.sleep(delay_seconds)

    print("\nاكتمل نشر سلسلة الإطلاق بنجاح.")


def main() -> None:
    parser = argparse.ArgumentParser(description="نشر سلسلة تغريدات إطلاق Luma Store على X.")
    parser.add_argument("--media", type=Path, default=None)
    parser.add_argument("--publish", action="store_true", help="تفعيل النشر الفعلي مع طلب الموافقة الصريحة.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        publish_thread(
            tweets=LAUNCH_THREAD,
            media_path=args.media,
            dry_run=(not args.publish) or args.dry_run,
        )
    except tweepy.Forbidden as exc:
        print(
            "خطأ صلاحيات (403 Forbidden): تأكد من أن صلاحيات التطبيق في X Developer Portal "
            "مضبوطة على 'Read and Write' وأنك أعدت توليد Access Token بعد تغييرها.\n"
            f"التفاصيل: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"تعذر إتمام العملية: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
