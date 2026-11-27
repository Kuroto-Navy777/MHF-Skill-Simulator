"""Foreground startup feedback. The main thread owns Tk; workers only report progress."""
import logging
import queue
import threading

LOG = logging.getLogger('launcher')
STAGES = {
    'Startup: recovering': '前回の状態を確認しています…',
    'Startup: checking releases': '最新版を確認しています…',
    'Update: checking signed manifest': '署名・更新情報を確認しています…',
    'Update: downloading launcher': 'ランチャーを取得しています…',
    'Update: downloading delta': '差分ファイルを取得しています…',
    'Update: downloading full payload': '完全版ファイルを取得しています…',
    'Update: verifying download': '取得ファイルの安全性を確認しています…',
    'Update: staging payload': '更新ファイルを展開・検査しています…',
    'Update: validating and replacing payload': '整合性検査とアプリの入れ替え中…',
    'Startup: rollback': '更新前のバージョンに復元しています…',
    'Startup: loading': 'データベースと画面を読み込んでいます…',
}


class StageHandler(logging.Handler):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def emit(self, record):
        stage = STAGES.get(record.getMessage())
        if stage:
            self.messages.put(stage)
        elif record.msg == 'Update bytes: %s / %s' and isinstance(record.args, tuple) and len(record.args) == 2:
            self.messages.put(record.args)


def download_display(received, total):
    # Signed asset sizes are authoritative; never present a global update percentage.
    if type(received) is not int or type(total) is not int or not 0 <= received <= total or total <= 0:
        return None
    percent = received / total * 100
    return percent, f'{received / 1048576:.1f} / {total / 1048576:.1f} MiB  ({percent:.0f}%)'


class StartupProgress:
    def __init__(self, install_root=None, enabled=True):
        self.root = None
        self.messages = queue.SimpleQueue()
        self.handler = StageHandler(self.messages)
        self.attached = False
        if not enabled:
            return
        try:
            import tkinter as tk
            from tkinter import ttk
            self.root = tk.Tk()
            root = self.root
            root.title('MHF Skill Simulator')
            root.resizable(False, False)
            if install_root is not None:
                try:
                    root.iconbitmap(str(install_root / 'app' / 'web' / 'favicon.ico'))
                except Exception:
                    pass
            root.protocol('WM_DELETE_WINDOW', lambda: None)
            frame = ttk.Frame(root, padding=24)
            frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='MHF Skill Simulator', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
            self.status = ttk.Label(frame, text='アプリを起動しています…', width=52, wraplength=420)
            self.status.pack(anchor='w', pady=(12, 8))
            self.bar = ttk.Progressbar(frame, mode='indeterminate', length=420)
            self.bar.pack(fill='x')
            self.detail = ttk.Label(frame, text='処理中です。完了後にアプリが開きます。', width=52)
            self.detail.pack(anchor='w', pady=(8, 0))
            root.update_idletasks()
            w, h = root.winfo_reqwidth(), root.winfo_reqheight()
            root.geometry(f'+{max(0,(root.winfo_screenwidth()-w)//2)}+{max(0,(root.winfo_screenheight()-h)//2)}')
            root.deiconify()
            root.lift()
            self.bar.start(80)
            root.update()
            LOG.addHandler(self.handler)
            self.attached = True
        except Exception:
            LOG.warning('Startup progress UI unavailable', exc_info=True)
            self.close()

    @property
    def active(self):
        return self.root is not None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        # A failed or closed status window must not interrupt the signed update.
        if self.attached:
            LOG.removeHandler(self.handler)
            self.attached = False
        root, self.root = self.root, None
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

    def pump(self):
        if not self.active:
            return
        try:
            while not self.messages.empty():
                message = self.messages.get_nowait()
                if isinstance(message, tuple):
                    value = download_display(*message)
                    if value is not None:
                        self.bar.stop()
                        self.bar.configure(mode='determinate', maximum=100, value=value[0])
                        self.detail.configure(text=value[1])
                else:
                    self.status.configure(text=message)
                    self.bar.stop()
                    self.bar.configure(mode='indeterminate', value=0)
                    self.bar.start(80)
                    self.detail.configure(text='処理中です。完了後にアプリが開きます。')
            self.root.update()
        except Exception:
            LOG.warning('Startup progress window failed', exc_info=True)
            self.close()

    def show(self, message):
        if self.active:
            self.messages.put(message)
            self.pump()

    def confirm_update(self, version, launcher_needed, app_needed):
        # No invisible consent dialog on login or if Tk could not start.
        if not self.active:
            return False
        from tkinter import messagebox
        components = 'ランチャーとアプリ本体' if launcher_needed and app_needed else ('ランチャー' if launcher_needed else 'アプリ本体')
        self.show(f'新しいバージョン {version} が見つかりました。')
        return messagebox.askyesno('更新があります', f'{components}の更新 {version} が利用できます。\n今すぐ更新しますか？\n\n「いいえ」で現在のバージョンを起動します。', parent=self.root)

    def run(self, action, *args, **kwargs):
        if not self.active:
            return action(*args, **kwargs)
        result, error = [], []

        def work():
            try:
                result.append(action(*args, **kwargs))
            except BaseException as exc:
                error.append(exc)

        worker = threading.Thread(target=work, name='startup-prepare')
        worker.start()
        try:
            while worker.is_alive():
                self.pump()
                worker.join(.05)
        finally:
            worker.join()
        self.pump()
        if error:
            raise error[0]
        return result[0]


def with_progress(action, *args, **kwargs):
    # Compatibility wrapper for older callers and regression tests.
    with StartupProgress(args[0] if args else None) as progress:
        return progress.run(action, *args, **kwargs)
