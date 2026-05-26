# 🚀 EcoSort AI — Command Cheatsheet

**Everything you need to run the robot yourself, without Claude.**
All commands are copy-paste. Pi user is `ben`, password is `Ben1234.`, Pi IP is
`192.168.219.105`.

---

## 1. Connect to the Pi

In Windows PowerShell on your laptop:

```
ssh ben@192.168.219.105
```

Type `Ben1234.` at the password prompt (nothing shows as you type — that's
normal). You're now "inside" the Pi.

---

## 2. Start / stop the robot

### Start it (keeps running after you close the terminal)
```
cd ~/ecosort-ai
nohup .venv/bin/python -m backend.main > ecosort.log 2>&1 &
```

### Stop it
```
kill -9 $(pgrep -f '[b]ackend.main')
```

### Is it running?
```
pgrep -af '[b]ackend.main' || echo 'not running'
```

---

## 3. Open the dashboard

On your **laptop browser**:

```
http://192.168.219.105:8000
```

Quick check from the Pi itself:

```
curl -s http://localhost:8000/api/status
```

---

## 4. Switch between real camera and simulation

Edit the config file:

```
nano ~/ecosort-ai/config.yaml
```

Find `CAMERA_BACKEND:` and set:

| Value | Meaning |
|---|---|
| `"auto"` | use the **real** Pi Camera (when the cable works) |
| `"simulation"` | fake camera — the full sort flow still demos (real servo still moves) |
| `"opencv"` | a USB webcam |

Save: **Ctrl+O → Enter → Ctrl+X**. Then restart EcoSort (Section 2).

---

## 5. Test the camera (without running EcoSort)

Stop EcoSort first, then:

```
timeout -k 5 18 rpicam-still -o /tmp/cam.jpg -t 2000 -n
ls -la /tmp/cam.jpg
```

- File size **> 20 000 bytes** → camera works → set `CAMERA_BACKEND: "auto"`
- File size **0 / errors** → cable or port is faulty

---

## 6. See the logs

EcoSort's live log:

```
tail -f ~/ecosort-ai/ecosort.log
```

Press **Ctrl+C** to stop following.

Camera-related kernel messages:

```
sudo dmesg | grep -iE 'imx|ov5647|csi|camera' | tail -20
```

---

## 7. Update the code from GitHub

```
cd ~/ecosort-ai
git pull
```

Then restart EcoSort.

---

## 8. Make it auto-start on power-up

So you never have to start it by hand again. **Run these once:**

```
sudo cp ~/ecosort-ai/scripts/ecosort.service /etc/systemd/system/
sudo nano /etc/systemd/system/ecosort.service
```

In the editor, change `User=pi` to `User=ben`, and the two paths from
`/home/pi/...` to `/home/ben/...`. Save (Ctrl+O → Enter → Ctrl+X). Then:

```
sudo systemctl daemon-reload
sudo systemctl enable ecosort.service
sudo systemctl start ecosort.service
```

After that, it launches itself on every boot. Manage it with:

| Command | What it does |
|---|---|
| `sudo systemctl start   ecosort.service` | start |
| `sudo systemctl stop    ecosort.service` | stop  |
| `sudo systemctl restart ecosort.service` | restart |
| `sudo systemctl status  ecosort.service` | check  |
| `journalctl -u ecosort.service -f` | follow the log live |

---

## 9. Reset stuck stuff

If anything misbehaves:

```
kill -9 $(pgrep -f '[b]ackend.main') 2>/dev/null
kill -9 $(pgrep -f '[r]picam')        2>/dev/null
sudo reboot
```

---

## 10. File locations on the Pi

| What | Where |
|---|---|
| Project | `~/ecosort-ai` |
| Config  | `~/ecosort-ai/config.yaml` |
| YOLO model (auto-downloaded) | `~/ecosort-ai/yolov8n.pt` |
| Log | `~/ecosort-ai/ecosort.log` |
| Database | `~/ecosort-ai/ecosort.db` |
| 👎 feedback images | `~/ecosort-ai/edge_ai/feedback_images/` |
| Python venv | `~/ecosort-ai/.venv/` |

---

## Quick reference card (the 6 you'll use most)

```bash
ssh ben@192.168.219.105                                  # 1. get in
cd ~/ecosort-ai && nohup .venv/bin/python -m backend.main > ecosort.log 2>&1 &   # 2. start
kill -9 $(pgrep -f '[b]ackend.main')                     # 3. stop
tail -f ~/ecosort-ai/ecosort.log                         # 4. watch the log
nano ~/ecosort-ai/config.yaml                            # 5. change settings
cd ~/ecosort-ai && git pull                              # 6. update
```

And on your **laptop**: open **`http://192.168.219.105:8000`** to see the dashboard.
