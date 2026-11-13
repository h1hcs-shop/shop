"""Pre-push / CI secret scan. Fails (exit 1) on anything that looks like a credential or a private identifier.
Prints file:line and the RULE name only, never the matched text."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = [
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("storefront_agent_id", re.compile(r"agent_[0-9a-f]{6,}")),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("generic_secret_assign", re.compile(r"(?i)\b(token|secret|passw(or)?d|api[_-]?key)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
    ("long_numeric_id", re.compile(r"(?<![\w.])-?\d{9,}(?![\w.])")),           # telegram user / chat / group ids
    ("tron_address", re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")),
    ("evm_address", re.compile(r"\b0x[0-9a-fA-F]{40}\b")),
    ("telegram_link", re.compile(r"t\.me/")),
    ("chat_id_field", re.compile(r"(?i)\b(chat_id|owner_id|user_id|group_id)\s*[:=]\s*-?\d")),
    ("private_path", re.compile(r"/workspace/|/home/h1hbot|C:\\\\Users")),
]
# shop_cart.py is vendored byte-for-byte from the bot: its user_id/chat_id SQL columns and t.me-free code are fine;
# rules listed here are skipped for that file only.
ALLOW = {"tools/vendor/shop_cart.py": {"chat_id_field"}, "tools/secret_scan.py": {r for r, _ in RULES}}
# Exact single-line exemptions (rule, file, full-line regex). site/app.js builds the PUBLIC 客服 chat link for the v3
# one-tap jump (Telegram.WebApp.openTelegramLink needs a t.me URL; usernames come from catalog.json and are the ones the bot
# already shows). Any other t.me/ anywhere is still a finding.
ALLOW_LINES = [("telegram_link", "site/app.js",
                re.compile(r'^\s*if \(jump\) \{ try \{ tg\.openTelegramLink\("https://t\.me/" \+ user \+ "\?text=" \+ encodeURIComponent\(summary\(\)\)\); \} catch \(e\) \{\} \}$'))]
# site/catalog.json: product codes ("k":"<10 digits>") are hashes of public product names, not ids; strip them before scanning.
SANITIZE = {"site/catalog.json": re.compile(r'"k":"\d{1,12}"')}
SKIP_DIRS = {".git", "__pycache__", ".cache"}
TEXT = (".py", ".js", ".html", ".css", ".json", ".md", ".yml", ".yaml", ".txt", ".gitignore", "")


def scan(root=ROOT):
    hits = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            p = os.path.join(dp, f); rel = os.path.relpath(p, root).replace(os.sep, "/")
            if not f.endswith(TEXT) and "." in f:
                continue
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except Exception:
                hits.append((rel, 0, "unreadable_or_binary")); continue
            for i, line in enumerate(lines, 1):
                if rel in SANITIZE:
                    line = SANITIZE[rel].sub('"k":""', line)
                for name, rx in RULES:
                    if name in ALLOW.get(rel, ()):
                        continue
                    if rx.search(line):
                        if any(r == name and f == rel and lx.match(line) for r, f, lx in ALLOW_LINES):
                            continue
                        hits.append((rel, i, name))
    return hits


if __name__ == "__main__":
    h = scan()
    for rel, i, name in h:
        print("%s:%d %s" % (rel, i, name))
    print("secret scan: %d finding(s)" % len(h))
    sys.exit(1 if h else 0)
