import os
import sys
import ast
import subprocess
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================

OWNER_ID = int(os.getenv("OWNER_ID", "5840953778"))
BOT_TOKEN = os.getenv("HOST_BOT_TOKEN", "8793201728:AAEtgdsLNpZzk7PN3UMPD97RsySivjnCTJQ")

BASE = Path("host_data")
FILES = BASE / "files"
RUNS = BASE / "runs"

FILES.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(parents=True, exist_ok=True)

# Required by FAKEMAIL.py
ALLOWED_IMPORTS = {
    # Python standard library
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii",
    "bisect", "calendar", "cmath", "collections", "concurrent", "configparser",
    "contextlib", "copy", "csv", "datetime", "decimal", "difflib", "email",
    "enum", "errno", "fractions", "functools", "gc", "getpass", "gettext",
    "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "linecache", "logging",
    "math", "mimetypes", "numbers", "operator", "os", "pathlib", "pprint",
    "queue", "random", "re", "secrets", "selectors", "shlex", "statistics",
    "string", "struct", "textwrap", "time", "timeit", "traceback", "types",
    "typing", "unicodedata", "urllib", "uuid", "warnings", "weakref", "xml",
    "zipfile",

    # Common third-party packages
    "aiohttp", "bs4", "flask", "fastapi", "httpx", "numpy", "pandas",
    "PIL", "psutil", "pytz", "requests", "telegram", "urllib3",
}

BLOCKED_IMPORTS = {
    "subprocess",
    "socket",
    "ctypes",
    "multiprocessing",
    "shutil",
    "resource",
    "signal",
    "pty",
    "fcntl",
    "pickle",
    "marshal",
    "builtins",
    "importlib",
}

processes = {}


# =========================
# HELPERS
# =========================

def is_owner(user_id):
    return user_id == OWNER_ID


def safe_name(name):
    name = Path(name).name

    if not name:
        return None

    if name.startswith("."):
        return None

    if not name.endswith(".py"):
        return None

    return name


def check_imports(path):
    tree = ast.parse(
        path.read_text(encoding="utf-8")
    )

    bad = set()

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):

            for item in node.names:
                module = item.name.split(".")[0]

                if (
                    module in BLOCKED_IMPORTS
                    or module not in ALLOWED_IMPORTS
                ):
                    bad.add(module)

        elif isinstance(node, ast.ImportFrom):

            module = (node.module or "").split(".")[0]

            if (
                module in BLOCKED_IMPORTS
                or module not in ALLOWED_IMPORTS
            ):
                bad.add(module)

    return sorted(bad)


def get_files():
    return sorted(
        [
            p.name
            for p in FILES.glob("*.py")
            if p.is_file()
        ]
    )


def is_running(name):
    p = processes.get(name)

    return (
        p is not None
        and p.poll() is None
    )


def get_status(name):
    p = processes.get(name)

    if p is None:
        return "⚪ Not running"

    code = p.poll()

    if code is None:
        return f"🟢 Running • PID `{p.pid}`"

    if code == 0:
        return "⚪ Stopped normally"

    return f"🔴 Stopped • Exit code `{code}`"


def log_file(name):
    return RUNS / f"{name}.log"


def read_logs(name):
    path = log_file(name)

    if not path.exists():
        return "No logs yet."

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return text[-3500:] or "No output yet."

    except Exception as e:
        return f"Log error: {e}"


# =========================
# MAIN MENU
# =========================

def main_keyboard():

    rows = [
        [
            InlineKeyboardButton(
                "📂 My Files",
                callback_data="files"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Status",
                callback_data="status"
            ),
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="refresh"
            )
        ]
    ]

    return InlineKeyboardMarkup(rows)


def file_keyboard(name):

    running = is_running(name)

    if running:

        control = InlineKeyboardButton(
            "🛑 Stop",
            callback_data=f"stop:{name}"
        )

    else:

        control = InlineKeyboardButton(
            "▶️ Start",
            callback_data=f"start:{name}"
        )

    return InlineKeyboardMarkup([
        [
            control,
            InlineKeyboardButton(
                "📄 Logs",
                callback_data=f"logs:{name}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data=f"file:{name}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="files"
            )
        ]
    ])


# =========================
# HOME
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    await update.message.reply_text(
        "🌌 𝐏𝐘𝐓𝐇𝐎𝐍 𝐇𝐎𝐒𝐓\n\n"
        "📤 Send a `.py` file to upload it.\n\n"
        "👇 Manage your files using buttons.",
        reply_markup=main_keyboard()
    )


# =========================
# FILE UPLOAD
# =========================

async def upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    doc = update.message.document

    if not doc:
        return

    name = safe_name(doc.file_name)

    if not name:

        await update.message.reply_text(
            "❌ Sirf valid `.py` file upload karo."
        )

        return

    path = FILES / name

    try:

        tg_file = await doc.get_file()

        await tg_file.download_to_drive(
            custom_path=str(path)
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Upload failed:\n{e}"
        )

        return

    # Syntax + import check
    try:

        bad = check_imports(path)

    except SyntaxError as e:

        path.unlink(missing_ok=True)

        await update.message.reply_text(
            f"❌ Syntax error:\n{e}"
        )

        return

    except Exception as e:

        path.unlink(missing_ok=True)

        await update.message.reply_text(
            f"❌ File check failed:\n{e}"
        )

        return

    if bad:

        path.unlink(missing_ok=True)

        await update.message.reply_text(
            "❌ Unsupported/blocked imports:\n\n"
            + "\n".join(
                f"• {x}"
                for x in bad
            )
        )

        return

    await update.message.reply_text(
        f"✅ 𝐔𝐏𝐋𝐎𝐀𝐃𝐄𝐃\n\n"
        f"📄 `{name}`\n"
        f"⚪ Status: Not running\n\n"
        f"👇 Press Start to run it.",
        parse_mode="Markdown",
        reply_markup=file_keyboard(name)
    )


# =========================
# START FILE
# =========================

async def start_process(name):

    name = safe_name(name)

    if not name:
        return False, "Invalid filename."

    path = FILES / name

    if not path.exists():
        return False, "File not found."

    if is_running(name):
        return False, "Already running."

    try:
        bad = check_imports(path)

        if bad:
            return False, (
                "Blocked imports: "
                + ", ".join(bad)
            )

        logfile = log_file(name)

        fp = open(
            logfile,
            "a",
            encoding="utf-8"
        )

        fp.write(
            "\n\n===== START =====\n"
        )
        fp.flush()

        # IMPORTANT FIX:
        # cwd is FILES, so only filename is passed.
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                name
            ],
            cwd=str(FILES),
            stdin=subprocess.DEVNULL,
            stdout=fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )

        processes[name] = process

        return True, process.pid

    except Exception as e:
        return False, str(e)


# =========================
# STOP FILE
# =========================

async def stop_process(name):

    name = safe_name(name)

    if not name:
        return False, "Invalid filename."

    process = processes.get(name)

    if not process:
        return False, "Process is not running."

    if process.poll() is not None:
        return False, "Process is already stopped."

    try:

        process.terminate()

        return True, "Stopped"

    except Exception as e:

        return False, str(e)


# =========================
# CALLBACKS
# =========================

async def callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not is_owner(
        query.from_user.id
    ):
        return

    data = query.data

    # ---------------------
    # FILE LIST
    # ---------------------

    if data in ("files", "refresh"):

        files = get_files()

        if not files:

            await query.edit_message_text(
                "📂 𝐌𝐘 𝐅𝐈𝐋𝐄𝐒\n\n"
                "No Python files uploaded yet.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏠 Home",
                            callback_data="home"
                        )
                    ]
                ])
            )

            return

        buttons = []

        for name in files:

            if is_running(name):
                icon = "🟢"
            else:
                icon = "⚪"

            buttons.append([
                InlineKeyboardButton(
                    f"{icon} {name}",
                    callback_data=f"file:{name}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home"
            )
        ])

        await query.edit_message_text(
            "📂 𝐌𝐘 𝐅𝐈𝐋𝐄𝐒\n\n"
            "🟢 Running\n"
            "⚪ Stopped\n\n"
            "Select a file:",
            reply_markup=InlineKeyboardMarkup(
                buttons
            )
        )

        return

    # ---------------------
    # HOME
    # ---------------------

    if data == "home":

        await query.edit_message_text(
            "🌌 𝐏𝐘𝐓𝐇𝐎𝐍 𝐇𝐎𝐒𝐓\n\n"
            "📤 Send a `.py` file to upload it.\n\n"
            "👇 Manage your files:",
            reply_markup=main_keyboard()
        )

        return

    # ---------------------
    # STATUS
    # ---------------------

    if data == "status":

        files = get_files()

        if not files:

            text = "📊 𝐒𝐓𝐀𝐓𝐔𝐒\n\nNo files."

        else:

            lines = []

            for name in files:

                lines.append(
                    f"📄 `{name}`\n"
                    f"{get_status(name)}\n"
                )

            text = (
                "📊 𝐇𝐎𝐒𝐓 𝐒𝐓𝐀𝐓𝐔𝐒\n\n"
                + "\n".join(lines)
            )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

        return

    # ---------------------
    # FILE PAGE
    # ---------------------

    if data.startswith("file:"):

        name = safe_name(
            data[5:]
        )

        if not name:
            return

        await query.edit_message_text(
            f"📄 𝐅𝐈𝐋𝐄\n\n"
            f"Name: `{name}`\n\n"
            f"Status:\n"
            f"{get_status(name)}",
            parse_mode="Markdown",
            reply_markup=file_keyboard(name)
        )

        return

    # ---------------------
    # START
    # ---------------------

    if data.startswith("start:"):

        name = safe_name(
            data[6:]
        )

        if not name:
            return

        success, result = await start_process(
            name
        )

        if success:

            text = (
                f"🟢 𝐒𝐓𝐀𝐑𝐓𝐄𝐃\n\n"
                f"📄 `{name}`\n"
                f"🆔 PID: `{result}`\n\n"
                f"Status: 🟢 Running"
            )

        else:

            text = (
                f"❌ 𝐒𝐓𝐀𝐑𝐓 𝐅𝐀𝐈𝐋𝐄𝐃\n\n"
                f"📄 `{name}`\n\n"
                f"{result}\n\n"
                f"📄 Check Logs."
            )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=file_keyboard(name)
        )

        return

    # ---------------------
    # STOP
    # ---------------------

    if data.startswith("stop:"):

        name = safe_name(
            data[5:]
        )

        if not name:
            return

        success, result = await stop_process(
            name
        )

        if success:

            text = (
                f"🛑 𝐒𝐓𝐎𝐏𝐏𝐄𝐃\n\n"
                f"📄 `{name}`"
            )

        else:

            text = (
                f"❌ {result}"
            )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=file_keyboard(name)
        )

        return

    # ---------------------
    # LOGS
    # ---------------------

    if data.startswith("logs:"):

        name = safe_name(
            data[5:]
        )

        if not name:
            return

        text = read_logs(name)

        if len(text) > 3500:
            text = text[-3500:]

        await query.edit_message_text(
            f"📄 𝐋𝐎𝐆𝐒 — `{name}`\n\n"
            f"{text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Refresh Logs",
                        callback_data=f"logs:{name}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=f"file:{name}"
                    )
                ]
            ])
        )

        return


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise SystemExit(
            "HOST_BOT_TOKEN set karo."
        )

    if not OWNER_ID:
        raise SystemExit(
            "OWNER_ID set karo."
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            upload
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            callback
        )
    )

    print(
        "PYTHON HOST STARTED"
    )

    app.run_polling()


if __name__ == "__main__":
    main()