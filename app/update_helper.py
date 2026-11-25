"""3.12: installs an update «только изменения».

The program has assembled the new version next to itself and checked every file of it against the signed manifest
(updates.py). This small exe then does what the full installer does: asks the program to close (it saves everything
and makes a backup on exit), puts the new folder in place of the old one and opens the program again. If anything
fails, the old version stays (swap.swap_in puts it back), is opened again, and the program remembers to download this
update whole next time.

    dd-update-helper.exe <job.json>    job: {stage, target, exe, title, name, failed, args}

Standard library and swap.py only — no config, no version inside: build.ps1 builds it once per its own source, so the
same file is in every version and an update «только изменения» carries it only when this code changes.
"""
from __future__ import annotations

import json
import os
import sys
import time

import swap

RETRIES = 3
RETRY_S = 2.0


def _mark_failed(job, why):
    try:
        with open(job["failed"], "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {why}\n")
    except (KeyError, OSError):
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        with open(argv[0], encoding="utf-8") as f:
            job = json.load(f)
        target_dir, stage, exe = job["target"], job["stage"], job["exe"]
    except (IndexError, OSError, ValueError, KeyError, TypeError) as e:
        swap.message(f"Не удалось установить обновление: {e}", "Обновление")
        return 2
    title, name = job.get("title") or "", job.get("name") or "Программа"
    args = [str(a) for a in job.get("args") or []]
    target = os.path.join(target_dir, exe)
    # М17: wait as long as the open program needs to save and back up; never leave the computer without it
    while not swap.close_running(target, title):
        if swap.ask_retry(f"{name} ещё закрывается: сохраняет данные и резервную копию.\n\n«Повторить» — подождать ещё.\n"
                          "«Отмена» — не обновлять сейчас: программа останется открытой.", title):
            continue
        if swap.close_running(target, title, seconds=1):  # it closed while the question was on the screen
            swap.launch(target, args)
        return 1  # the checked folder stays: «Обновить сейчас» uses it again
    failed = None
    for _ in range(RETRIES):  # an antivirus may hold a file it is checking for a moment
        try:
            swap.swap_in(stage, target_dir, exe, keep_stage=True)
            failed = None
            break
        except Exception as e:  # noqa: BLE001
            failed = e
            if not getattr(e, "restored", False):  # not a failed move put back (e.g. the folder is gone): no retry
                break
            time.sleep(float(job.get("retry_s", RETRY_S)))
    swap.rmtree_quiet(stage)
    if failed:
        _mark_failed(job, failed)
    if os.path.exists(target):  # the new version, or the old one when the update failed — always open again
        swap.launch(target, args)
    if failed:
        swap.message(f"Не удалось установить обновление {name}: {failed}\n\n"
                     + ("Программа открыта в прежней версии. " if os.path.exists(target) else "")
                     + "Нажмите «Обновить» ещё раз — программа скачает обновление целиком.", title)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
