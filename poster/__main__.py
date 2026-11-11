"""Entry point.  python -m poster <command>

Commands: run (login check + post due rows), login, test-check, test-post
"""
import os
import sys

from . import publish, testpost, tokens
from .common import load_config, load_state, now_utc, save_state
from .linkedin import LinkedIn
from .notion import Notion


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "run"
    cfg = load_config()
    state = load_state()
    now = now_utc()

    if cmd == "login":
        return tokens.login(cfg, state, os.environ.get("ISSUE_BODY", ""),
                            os.environ.get("ISSUE_NUMBER", ""), now)

    print(f"Run at {now.isoformat()} | dry_run={cfg.get('dry_run')} | paused={cfg.get('paused')}")
    tok = tokens.check(cfg, state, now)
    save_state(state)
    if not os.environ.get("NOTION_TOKEN"):
        return 0  # the "Setup is not finished" issue already says what to do
    notion = Notion(os.environ["NOTION_TOKEN"], cfg["notion"])
    li = LinkedIn(tok["access_token"], tok["person_id"], cfg["linkedin"]) if tok else None

    if cmd == "test-check":
        return testpost.check(cfg, state, notion, li, tok, now)
    if cmd == "test-post":
        code = testpost.post(cfg, state, notion, li, now, os.environ.get("TEST_ROW", ""),
                             os.environ.get("CONFIRM", ""))
        save_state(state)
        return code

    publish.run(cfg, state, notion, li, now)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
