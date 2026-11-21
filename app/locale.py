"""Persian wording for API errors. The UI also translates static strings."""

from __future__ import annotations

FA = {
    "Sign in to continue.": "برای ادامه وارد شوید.",
    "Administrator access is required.": "دسترسی مدیر لازم است.",
    "Enter a valid email address.": "یک نشانی ایمیل معتبر وارد کنید.",
    "Use a password of at least 8 characters.": "گذرواژه باید حداقل ۸ نویسه باشد.",
    "An account with that email already exists.": "حسابی با این ایمیل وجود دارد.",
    "Registration on the public demo requires an access code. Use the limited trial, or ask an administrator for a code.": "ثبت‌نام در نسخه نمایشی عمومی به کد دسترسی نیاز دارد. از آزمایش محدود استفاده کنید یا از مدیر کد بگیرید.",
    "Email or password is not valid.": "ایمیل یا گذرواژه درست نیست.",
    "This account is disabled.": "این حساب غیرفعال است.",
    "The anonymous trial is turned off.": "آزمایش ناشناس خاموش است.",
    "Trial sessions do not have a password.": "نشست آزمایشی گذرواژه ندارد.",
    "Sign up before redeeming a code. The trial cannot hold a code.": "پیش از استفاده از کد، حساب بسازید. آزمایش نمی‌تواند کد را نگه دارد.",
    "That access code is not valid.": "این کد دسترسی معتبر نیست.",
    "That access code has been revoked.": "این کد دسترسی باطل شده است.",
    "That access code has expired.": "مهلت این کد دسترسی گذشته است.",
    "That access code has already been used.": "این کد دسترسی قبلاً استفاده شده است.",
    "That code does not grant registration.": "این کد اجازه ثبت‌نام نمی‌دهد.",
    "This account has already redeemed that code.": "این حساب قبلاً این کد را استفاده کرده است.",
    "The trial uses the prepared demo project. Create an account to open your own.": "آزمایش فقط پروژه آماده را می‌بیند. برای پروژه خودتان حساب بسازید.",
    "A project with that code already exists.": "پروژه‌ای با این کد وجود دارد.",
    "Select at least one knowledge scope.": "حداقل یک محدوده دانش را انتخاب کنید.",
    "Only the project owner can change or delete it.": "فقط مالک پروژه می‌تواند آن را تغییر دهد یا حذف کند.",
    "Enter a project name of at least 2 characters.": "نام پروژه باید حداقل ۲ نویسه باشد.",
    "The public demo allows two projects per account.": "نسخه نمایشی عمومی برای هر حساب دو پروژه اجازه می‌دهد.",
    "Upload a PDF, Excel workbook, text file, or image.": "یک PDF، پرونده اکسل، متن، یا تصویر بارگذاری کنید.",
    "Project not found.": "پروژه پیدا نشد.",
    "Document not found.": "سند پیدا نشد.",
    "Folder not found.": "پوشه پیدا نشد.",
    "Folders can only be nested two levels deep.": "پوشه‌ها حداکثر دو سطح می‌توانند تو در تو باشند.",
    "Folder is not empty.": "پوشه خالی نیست.",
    "Codes and standards stay in their own section.": "کدها و استانداردها در بخش خودشان می‌مانند.",
    "Connect Google Drive before uploading files.": "پیش از بارگذاری، گوگل‌درایو خود را وصل کنید.",
    "Google Drive rejected the upload. Connect Drive again and retry.": "گوگل‌درایو بارگذاری را نپذیرفت. دوباره وصل شوید و تلاش کنید.",
    "Sign in before connecting Google Drive.": "پیش از وصل کردن گوگل‌درایو وارد شوید.",
    "That file is empty.": "پرونده خالی است.",
    "A mentioned document was not found.": "یکی از سندهای اشاره‌شده پیدا نشد.",
    "Conversation not found.": "گفتگو پیدا نشد.",
    "You do not have access to that project.": "به این پروژه دسترسی ندارید.",
    "The trial can read the demo project. Uploads and edits need a signed-in account.": "آزمایش فقط می‌تواند پروژه نمایشی را بخواند. بارگذاری به حساب کاربری نیاز دارد.",
    "You do not have write access to that project.": "اجازه ویرایش این پروژه را ندارید.",
    "Uploads are turned off for the anonymous trial. Sign in with an account that has project access.": "بارگذاری برای آزمایش ناشناس خاموش است. با حسابی که به پروژه دسترسی دارد وارد شوید.",
    "Too many requests from this session. Wait a while and try again.": "درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.",
    "User not found.": "کاربر پیدا نشد.",
    "Code not found.": "کد پیدا نشد.",
    "Unknown plan.": "طرح ناشناخته است.",
    "A code can assign the free or pro plan.": "کد فقط می‌تواند طرح رایگان یا حرفه‌ای بدهد.",
    "Credits cannot be negative, and a code needs at least one use.": "اعتبار نمی‌تواند منفی باشد و کد حداقل یک بار مصرف دارد.",
    "Card billing is not enabled on this server.": "پرداخت کارتی روی این سرویس فعال نیست.",
    "Create an account before starting a subscription.": "پیش از اشتراک، یک حساب بسازید.",
    "Webhook signature could not be verified.": "امضای وبهوک تأیید نشد.",
    "Select a project before uploading.": "پیش از بارگذاری یک پروژه را انتخاب کنید.",
}


def localize_detail(detail, lang: str):
    if lang != "fa":
        return detail
    if isinstance(detail, str):
        if detail in FA:
            return FA[detail]
        if detail.startswith("That file is larger than"):
            return "حجم پرونده از سقف طرح بیشتر است."
        if detail.startswith("Upload limit reached"):
            return "سقف بارگذاری ۲۴ ساعت گذشته پر شده است."
        if detail.startswith("Unsupported file type"):
            return "این نوع پرونده پشتیبانی نمی‌شود. PDF، اکسل، متن، یا تصویر بفرستید."
        return detail
    if isinstance(detail, dict):
        copied = dict(detail)
        if copied.get("code") == "quota_exhausted":
            if copied.get("plan") == "trial":
                copied["message"] = "اعتبار آزمایش تمام شده است. برای ادامه حساب بسازید یا وارد شوید."
            else:
                reset = str(copied.get("reset_at") or "")[:10]
                copied["message"] = (
                    f"اعتبار ماهانه طرح {copied.get('plan', '')} تمام شده است. "
                    f"موجودی در {reset} نو می‌شود. مدیر می‌تواند اعتبار را افزایش دهد یا طرح را عوض کند."
                )
            return copied
        message = copied.get("message")
        if isinstance(message, str):
            copied["message"] = localize_detail(message, lang)
        return copied
    return detail
