#!/usr/bin/env python3
"""Detached upload worker: upload image to imgur, open Google Lens.

Usage: python3 upload.py <image_path> <imgur_client_id>
"""

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request


def notify(summary, body=None, icon=None, timeout=None):
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send"]
    if timeout is not None:
        cmd.extend(["-t", str(timeout)])
    if icon:
        cmd.extend(["-i", icon])
    cmd.append(summary)
    if body:
        cmd.append(body)
    subprocess.run(cmd, check=False)


def open_url(url):
    for launcher in ("omarchy-launch-browser", "xdg-open"):
        if shutil.which(launcher):
            subprocess.Popen(
                [launcher, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
    return False


def copy_image(path):
    mime_type = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        subprocess.run(["wl-copy", "-t", mime_type], stdin=f, check=False)


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: upload.py <path> <client_id>")

    path = sys.argv[1]
    client_id = sys.argv[2]

    notify("Circle to Search", "Uploading image...", icon="image-loading", timeout=5000)

    try:
        with open(path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode("ascii")

        payload = urllib.parse.urlencode({
            "image": encoded_image,
            "type": "base64",
        }).encode("ascii")

        request = urllib.request.Request(
            "https://api.imgur.com/3/image",
            data=payload,
            headers={"Authorization": f"Client-ID {client_id}"},
        )

        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.loads(response.read().decode("utf-8"))

        image_url = reply.get("data", {}).get("link")
        if reply.get("success") and image_url:
            lens_url = "https://lens.google.com/uploadbyurl?url=" + urllib.parse.quote(image_url)
            notify("Circle to Search", "Opening Google Lens...", icon="emblem-ok", timeout=2000)
            open_url(lens_url)
        else:
            raise RuntimeError("Imgur upload failed")
    except Exception:
        copy_image(path)
        notify("Upload Failed", "Image copied - paste manually", icon="dialog-warning")
        open_url("https://lens.google.com/")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
