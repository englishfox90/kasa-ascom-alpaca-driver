import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import keyring
import subprocess
import sys
import os
import threading
import time
import pystray
from PIL import Image, ImageDraw

SERVICE = 'kasa-alpaca'

class KasaManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Kasa Alpaca Switch Manager')
        self.root.geometry('400x350')
        self.root.resizable(False, False)
        self.server_process = None
        self.status_var = tk.StringVar()
        self.status_var.set('Server not running.')
        self.log_lines = []
        self.log_var = tk.StringVar()
        self.log_var.set('')
        self.tray_icon = None
        self._build_ui()
        self.root.protocol('WM_DELETE_WINDOW', self._on_minimize)
        self._update_status_periodically()
        self._first_run_check()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text='Kasa Alpaca Switch Manager', font=('Segoe UI', 16, 'bold')).pack(pady=(0, 10))
        ttk.Button(frm, text='Set/Update Credentials', command=self.set_credentials).pack(fill='x', pady=5)
        ttk.Button(frm, text='Start Server', command=self.start_server).pack(fill='x', pady=5)
        ttk.Button(frm, text='Stop Server', command=self.stop_server).pack(fill='x', pady=5)
        ttk.Label(frm, textvariable=self.status_var, foreground='blue', font=('Segoe UI', 10, 'italic')).pack(pady=(10, 0))
        ttk.Label(frm, text='Recent Log:', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(15, 0))
        self.log_text = tk.Text(frm, height=6, width=45, state='disabled', font=('Consolas', 9))
        self.log_text.pack(pady=(0, 5))
        ttk.Button(frm, text='Copy Server URL', command=self.copy_server_url).pack(fill='x', pady=2)
        ttk.Button(frm, text='Exit', command=self.on_exit).pack(side='bottom', fill='x', pady=5)
        self.progress = ttk.Progressbar(frm, mode='indeterminate')

    def _first_run_check(self):
        email = keyring.get_password(SERVICE, 'email')
        password = keyring.get_password(SERVICE, 'password')
        if not email or not password:
            messagebox.showinfo('Welcome', 'Welcome! Please set your Kasa credentials to begin.')
            self.set_credentials()

    def set_credentials(self):
        email = simpledialog.askstring('Email', 'Enter Kasa account email:', parent=self.root)
        if not email:
            return
        password = simpledialog.askstring('Password', 'Enter Kasa account password:', show='*', parent=self.root)
        if not password:
            return
        keyring.set_password(SERVICE, 'email', email)
        keyring.set_password(SERVICE, 'password', password)
        messagebox.showinfo('Credentials', 'Credentials updated successfully!')

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            messagebox.showinfo('Server', 'Server is already running.')
            return
        self.status_var.set('Starting server...')
        self.progress.pack(fill='x', pady=2)
        self.progress.start()
        def run():
            python_exe = sys.executable.replace('python.exe', 'pythonw.exe') if sys.platform == 'win32' else sys.executable
            app_path = os.path.join(os.path.dirname(__file__), 'app.py')
            self.server_process = subprocess.Popen(
                [python_exe, app_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            self.status_var.set('Server running.')
            self.progress.stop()
            self.progress.pack_forget()
            self._read_server_logs()
        threading.Thread(target=run, daemon=True).start()

    def stop_server(self):
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.status_var.set('Server stopped.')
        else:
            self.status_var.set('Server not running.')

    def _read_server_logs(self):
        def read_logs():
            if not self.server_process:
                return
            for line in self.server_process.stdout:
                self._append_log(line)
            for line in self.server_process.stderr:
                self._append_log(line)
        threading.Thread(target=read_logs, daemon=True).start()

    def _append_log(self, line):
        self.log_lines.append(line.strip())
        if len(self.log_lines) > 10:
            self.log_lines = self.log_lines[-10:]
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.insert(tk.END, '\n'.join(self.log_lines))
        self.log_text.config(state='disabled')

    def _update_status_periodically(self):
        if self.server_process and self.server_process.poll() is None:
            self.status_var.set('Server running at http://127.0.0.1:5555')
        self.root.after(2000, self._update_status_periodically)

    def copy_server_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append('http://127.0.0.1:5555')
        messagebox.showinfo('Copied', 'Server URL copied to clipboard!')

    def _on_minimize(self):
        self.root.withdraw()
        self._show_tray_icon()

    def _show_tray_icon(self):
        if self.tray_icon:
            return
        image = Image.new('RGB', (64, 64), color='white')
        d = ImageDraw.Draw(image)
        d.ellipse((16, 16, 48, 48), fill='blue')
        menu = pystray.Menu(
            pystray.MenuItem('Show', self._on_tray_show),
            pystray.MenuItem('Start Server', self.start_server),
            pystray.MenuItem('Stop Server', self.stop_server),
            pystray.MenuItem('Exit', self._on_tray_exit)
        )
        self.tray_icon = pystray.Icon('KasaSwitch', image, 'Kasa Switch Manager', menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _on_tray_show(self, icon=None, item=None):
        self.root.deiconify()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def _on_tray_exit(self, icon=None, item=None):
        self.on_exit()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def on_exit(self):
        self.stop_server()
        self.root.destroy()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if sys.platform == 'win32':
        style.theme_use('vista')
    else:
        style.theme_use('clam')
    app = KasaManagerApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
